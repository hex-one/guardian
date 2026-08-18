/**
 * Guardian Watchlist — Apps Script backend
 *
 * Paste this whole file into Extensions > Apps Script in your Google Sheet,
 * replacing whatever's there by default. See SETUP.md for the full
 * step-by-step (creating the sheet, deploying this, getting your two URLs).
 *
 * One sheet tab called "Watchlist" holds EVERYTHING -- pending submissions,
 * approved (live/blinking) entries, and cleared/rejected history all live
 * in the same tab, distinguished by the "status" column. One shared
 * memory, not a scattered one. Guardian's read-only sync only ever looks
 * at rows where status = "approved"; this script is what actually writes
 * to the sheet (submissions and reviews), since a published CSV export
 * is read-only.
 *
 * Columns (row 1 must be exactly this header row):
 *   user_id | display_name | reason | submitted_by | submitted_at | status | reviewed_by | reviewed_at | last_validated_at | category
 *
 * status is one of: pending, approved, cleared, rejected, pending_removal, removed
 *   (pending_removal = an approver still needs to confirm removing this
 *   entry; Guardian's read side treats it as still active/live until
 *   that happens, same as a brand-new pending entry isn't live until
 *   IT'S approved. "removed" is the terminal state once a removal is
 *   confirmed.)
 * category is one of: predator, stalker, troll, poi, vip, creator, other
 *   (predator/stalker/troll are treated as genuine threats and blink in
 *   Guardian's player list; poi/vip/creator are informational tags and
 *   just show steadily -- see watchlist_categories.py on the Guardian side)
 *
 * A SECOND tab, "VoteKicks", tracks vote-kicks Guardian observes in the
 * VRChat log -- see the comment above SHEET_NAME_VOTE_KICKS below for
 * its header row. Same script, same deployment, same two Config URLs;
 * just add the tab and this file already knows what to do with it.
 */

// ---- EDIT THIS: paste the VRChat user IDs (usr_...) of whoever is
// allowed to approve/reject/clear entries. Anyone else's review attempts
// get rejected by this script, server-side -- Guardian itself has no way
// to bypass this from the client side.
var APPROVER_ALLOWLIST = [
  "usr_REPLACE-WITH-A-REAL-APPROVER-ID",
  "usr_REPLACE-WITH-ANOTHER-APPROVER-ID",
];

var SHEET_NAME = "Watchlist";

// Column positions (1-indexed, matching the header row above)
var COL_USER_ID = 1;
var COL_DISPLAY_NAME = 2;
var COL_REASON = 3;
var COL_SUBMITTED_BY = 4;
var COL_SUBMITTED_AT = 5;
var COL_STATUS = 6;
var COL_REVIEWED_BY = 7;
var COL_REVIEWED_AT = 8;
var COL_LAST_VALIDATED_AT = 9;
var COL_CATEGORY = 10;

// ---- VoteKicks: a second tab on the SAME spreadsheet, riding along on
// the SAME deployed script and the SAME two Config URLs -- no separate
// setup needed for this one. Add a tab named exactly "VoteKicks" to
// this spreadsheet with this header row before using the feature:
//
//   event_id | target_user_id | target_display_name | world_id | instance_id | status | initiated_at | succeeded_at | submitted_by | submitted_at
//
// status is one of: initiated, succeeded
// event_id is computed CLIENT-SIDE (Guardian's vote_kicks.py) from
// world+instance+target+minute, so two different Guardians who watched
// the SAME real vote independently arrive at the SAME event_id without
// ever talking to each other directly -- that's what makes the
// first-come-first-served rejection below actually work.
var SHEET_NAME_VOTE_KICKS = "VoteKicks";

var VK_COL_EVENT_ID = 1;
var VK_COL_TARGET_USER_ID = 2;
var VK_COL_TARGET_DISPLAY_NAME = 3;
var VK_COL_WORLD_ID = 4;
var VK_COL_INSTANCE_ID = 5;
var VK_COL_STATUS = 6;
var VK_COL_INITIATED_AT = 7;
var VK_COL_SUCCEEDED_AT = 8;
var VK_COL_SUBMITTED_BY = 9;
var VK_COL_SUBMITTED_AT = 10;


function doPost(e) {
  var data = JSON.parse(e.postData.contents);
  var action = data.action;

  if (action === "submit") return handleSubmit(data);
  if (action === "review") return handleReview(data);
  if (action === "update_name") return handleUpdateName(data);
  if (action === "request_removal") return handleRequestRemoval(data);
  if (action === "submit_vote_kick") return handleSubmitVoteKick(data);

  return respond({ status: "error", message: "Unknown action: " + action });
}


function handleRequestRemoval(data) {
  // Removal needs review too, same as a new submission does -- this only
  // flips status to "pending_removal" rather than deleting the row.
  // Guardian's read side still treats "pending_removal" as active (see
  // fetch_master() on the Guardian side), so the player keeps showing up
  // until an approver actually confirms the removal via handleReview()
  // below (new_status "removed" to confirm, or "approved" to deny it and
  // keep them listed -- "approved" is already a valid status there, so
  // denying a removal needed no changes to handleReview at all).
  var sheet = getSheet();
  var rows = sheet.getDataRange().getValues();

  for (var i = 1; i < rows.length; i++) {
    if (rows[i][COL_USER_ID - 1] === data.user_id) {
      var currentStatus = rows[i][COL_STATUS - 1];
      if (currentStatus !== "approved") {
        return respond({
          status: "error",
          message: "Can only request removal for an approved entry (current status: " + currentStatus + ").",
        });
      }
      var rowNum = i + 1;
      sheet.getRange(rowNum, COL_STATUS).setValue("pending_removal");
      return respond({ status: "success" });
    }
  }

  return respond({ status: "error", message: "User ID not found on the sheet." });
}


function handleSubmit(data) {
  var sheet = getSheet();
  var rows = sheet.getDataRange().getValues();

  for (var i = 1; i < rows.length; i++) {
    if (rows[i][COL_USER_ID - 1] === data.user_id) {
      var existingStatus = rows[i][COL_STATUS - 1];
      var rowNum = i + 1;

      // "cleared" is the one status that can be resubmitted -- but only
      // when the client explicitly confirms it (Guardian shows a warning
      // naming the previous reviewer/date before setting this flag), and
      // even then this REUSES the existing row rather than creating a
      // second one for the same user_id, so history isn't duplicated.
      if (existingStatus === "cleared" && data.confirm_resubmit === true) {
        var now = new Date().toISOString();
        sheet.getRange(rowNum, COL_REASON).setValue(data.reason || "");
        sheet.getRange(rowNum, COL_SUBMITTED_BY).setValue(data.submitted_by || "");
        sheet.getRange(rowNum, COL_SUBMITTED_AT).setValue(now);
        sheet.getRange(rowNum, COL_STATUS).setValue("pending");
        sheet.getRange(rowNum, COL_REVIEWED_BY).setValue("");
        sheet.getRange(rowNum, COL_REVIEWED_AT).setValue("");
        sheet.getRange(rowNum, COL_CATEGORY).setValue(data.category || "other");
        return respond({ status: "success" });
      }

      return respond({
        status: "error",
        message: "Already on the list (status: " + existingStatus + ")",
      });
    }
  }

  var now = new Date().toISOString();
  sheet.appendRow([
    data.user_id,
    data.display_name || "",
    data.reason || "",
    data.submitted_by || "",
    now,
    "pending",
    "",
    "",
    now,
    data.category || "other",
  ]);

  return respond({ status: "success" });
}


function handleReview(data) {
  if (APPROVER_ALLOWLIST.indexOf(data.reviewer_id) === -1) {
    return respond({ status: "error", message: "You're not on the approver allowlist for this sheet." });
  }

  var validStatuses = ["approved", "cleared", "rejected", "removed"];
  if (validStatuses.indexOf(data.new_status) === -1) {
    return respond({ status: "error", message: "Invalid status: " + data.new_status });
  }

  var sheet = getSheet();
  var rows = sheet.getDataRange().getValues();

  for (var i = 1; i < rows.length; i++) {
    if (rows[i][COL_USER_ID - 1] === data.user_id) {
      var rowNum = i + 1; // getRange is 1-indexed
      sheet.getRange(rowNum, COL_STATUS).setValue(data.new_status);
      sheet.getRange(rowNum, COL_REVIEWED_BY).setValue(data.reviewer_id);
      sheet.getRange(rowNum, COL_REVIEWED_AT).setValue(new Date().toISOString());
      return respond({ status: "success" });
    }
  }

  return respond({ status: "error", message: "User ID not found on the sheet." });
}


function handleUpdateName(data) {
  // Opportunistic display-name refresh -- Guardian calls this when it
  // happens to see a watchlisted player under a different name than the
  // sheet has on file. No approver check needed; this never changes
  // status, reason, or anything moderation-relevant, just keeps the name
  // column current.
  var sheet = getSheet();
  var rows = sheet.getDataRange().getValues();

  for (var i = 1; i < rows.length; i++) {
    if (rows[i][COL_USER_ID - 1] === data.user_id) {
      var rowNum = i + 1;
      sheet.getRange(rowNum, COL_DISPLAY_NAME).setValue(data.display_name);
      sheet.getRange(rowNum, COL_LAST_VALIDATED_AT).setValue(new Date().toISOString());
      return respond({ status: "success" });
    }
  }

  return respond({ status: "error", message: "User ID not found on the sheet." });
}


function handleSubmitVoteKick(data) {
  // First come, first served -- one row per real-world event_id.
  // Reporting the SAME status twice (two Guardians who both caught the
  // initiation, or both caught the success independently) is a race
  // and loses to whoever's request landed here first. Reporting a NEW
  // status for an event that's already on the sheet (the initiation
  // was recorded earlier, this call is the success catching it up) is
  // real new information, not a race -- that one updates the row
  // instead of getting rejected.
  var sheet = getVoteKicksSheet();
  var rows = sheet.getDataRange().getValues();
  var now = new Date().toISOString();

  for (var i = 1; i < rows.length; i++) {
    if (rows[i][VK_COL_EVENT_ID - 1] === data.event_id) {
      var rowNum = i + 1;
      var existingStatus = rows[i][VK_COL_STATUS - 1];

      if (data.status === "succeeded" && existingStatus !== "succeeded") {
        sheet.getRange(rowNum, VK_COL_STATUS).setValue("succeeded");
        sheet.getRange(rowNum, VK_COL_SUCCEEDED_AT).setValue(data.succeeded_at || now);
        if (data.target_user_id && !rows[i][VK_COL_TARGET_USER_ID - 1]) {
          sheet.getRange(rowNum, VK_COL_TARGET_USER_ID).setValue(data.target_user_id);
        }
        return respond({ status: "success" });
      }

      return respond({
        status: "duplicate",
        message: "Another Guardian already submitted this event.",
      });
    }
  }

  sheet.appendRow([
    data.event_id,
    data.target_user_id || "",
    data.target_display_name || "",
    data.world_id || "",
    data.instance_id || "",
    data.status || "initiated",
    data.initiated_at || "",
    data.succeeded_at || "",
    data.submitted_by || "",
    now,
  ]);

  return respond({ status: "success" });
}


function getVoteKicksSheet() {
  var sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(SHEET_NAME_VOTE_KICKS);
  if (!sheet) {
    throw new Error('No tab named "' + SHEET_NAME_VOTE_KICKS + '" found. See SETUP.md.');
  }
  return sheet;
}


function getSheet() {
  var sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(SHEET_NAME);
  if (!sheet) {
    throw new Error('No tab named "' + SHEET_NAME + '" found. See SETUP.md.');
  }
  return sheet;
}


function respond(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}
