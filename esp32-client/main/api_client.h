#pragma once
#include <stdbool.h>

typedef struct {
    bool configured;
    bool authenticated;
    bool compatible;
    unsigned gate_ok;
    unsigned gate_failed;
} api_client_diagnostic;

/* Start the H2 REST worker. An empty URL keeps the device fully local. */
void api_client_start(const char *base_url);

/* Notify the worker after the station obtained an IP address. */
void api_client_network_up(void);

/* Schedule a sync after a locally completed recording. */
void api_client_queue_changed(void);
/* Ask for an immediate dashboard resync, independent of the queue or the
 * network coming back — the "pull past the top" refresh gesture. */
void api_client_request_sync(void);
/* Fetch one entity for the detail view. The result is handed back through
 * screen_entity_received; the request itself is queued for the worker, because
 * HTTP belongs to the worker and drawing belongs to the display task. */
void api_client_open_entity(const char *type, const char *id);
/* Mark an open task complete. The updated task (no longer carrying an
 * action) comes back through the same screen_entity_received the detail view
 * already redraws from. */
void api_client_complete_task(const char *task_id);
/* Durably queue a fixed server-proposed answer for one clarification. The
 * generated capture id is retained across retries, so POST remains idempotent. */
bool api_client_submit_capture(const char *content, const char *question_id);
/* Persist one list item's locally selected desired state. Staging never sends:
 * the list detail may toggle it back before the reader leaves. Committing
 * marks all staged changes ready for idempotent background delivery. A staged
 * draft found at boot is treated as an implicit leave and delivered. */
bool api_client_stage_list_item(const char *item_id, bool done);
bool api_client_commit_list_items(void);
/* Overlay a durable staged/queued desired state on a stale list detail. */
bool api_client_list_item_desired(const char *item_id, bool *done);
/* Fetch the session list for the history view. Same split as the detail: HTTP
 * belongs to the worker, drawing to the display task; the result comes back
 * through screen_history_received. */
void api_client_open_history(void);
/* Fetch a session dashboard requested by a server-driven card. History rows
 * show their complete device-facing state inline and do not call this path. */
void api_client_open_session(const char *session_id);

/* Content-free local state for the settings diagnostics. No URL, credential,
 * response body or user content crosses this boundary. */
api_client_diagnostic api_client_get_diagnostic(void);

/* Content-free diagnostics for USB tests. */
void api_client_report(void);
