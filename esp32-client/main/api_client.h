#pragma once

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
/* Fetch the session list for the history view. Same split as the detail: HTTP
 * belongs to the worker, drawing to the display task; the result comes back
 * through screen_history_received. */
void api_client_open_history(void);
/* Fetch the dashboard of one past recording, selected in the history view. The
 * response uses the same envelope as the home dashboard. */
void api_client_open_session(const char *session_id);

/* Content-free diagnostics for USB tests. */
void api_client_report(void);
