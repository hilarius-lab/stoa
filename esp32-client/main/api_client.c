#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdatomic.h>
#include <stdint.h>
#include <dirent.h>
#include <unistd.h>
#include <sys/stat.h>
#include <limits.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/semphr.h"
#include "esp_http_client.h"
#include "esp_crt_bundle.h"
#include "esp_log.h"
#include "esp_wifi.h"
#include "esp_heap_caps.h"
#include "esp_random.h"
#include "lwip/netdb.h"
#include "nvs.h"
#include "cJSON.h"
#include "journal.h"
#include "memo_queue.h"
#include "recorder.h"
#include "api_client.h"
#include "screen.h"
#include "diagnostic_log.h"
#include "refresh_policy.h"

/* Headroom, not a fit. The server projects the e-paper surface down to roughly
 * six kilobytes, so 8192 would have worked on paper — and a worst case measured
 * at 8181 bytes is not a margin, it is a coin toss whose losing side is a blank
 * panel with an HTTP 200 in the log. Doubling costs one transient allocation on
 * a device with eight megabytes of PSRAM. Keep this at or below SNAPSHOT_MAX in
 * screen.c: the snapshot is copied with snprintf, which truncates in silence. */
#define API_RESPONSE_MAX 16384
#define API_URL_MAX 320
#define API_CONTRACT "1"

/* How long the worker sleeps when nothing has woken it. Three cases, and until
 * today only the first of them existed.
 *
 * A pass that failed used to schedule nothing at all: with an empty queue the
 * wait was portMAX_DELAY, so the worker blocked until a reconnect, a finished
 * recording or a button press happened to poke it. A device that boots into a
 * DNS hiccup then sits there indefinitely — observed on 6 September, where a
 * single failed name lookup left an enrollment code unredeemed while it expired.
 *
 * A pass that succeeded scheduled nothing either, which meant an idle device
 * never refreshed its dashboard: the panel kept whatever snapshot the boot had
 * fetched and eventually marked it stale, and nothing ever went and got a newer
 * one. `transports.fallback_refresh` has always said polling; there simply was
 * none. */
#define API_RETRY_MIN_MS 15000
#define API_RETRY_MAX_MS 600000
/* Used only when the server states no cache window of its own. */

typedef struct {
    char *data;
    size_t used;
    size_t capacity;
    bool overflow;
} response_buffer;

typedef struct {
    unsigned gates_ok;
    unsigned gates_failed;
    unsigned creates_ok;
    unsigned creates_failed;  /* the server refused the create */
    unsigned replay_failed;   /* the journal did not yield a usable session */
    unsigned settled_skipped; /* already delivered, nothing left to do */
    unsigned abandoned;       /* a journal without a single segment and without an end */
    unsigned resync_impossible; /* server wants it back, the release already removed it */
    unsigned uploads_acked;
    unsigned uploads_failed;
    unsigned reconciled;
    unsigned resynced;   /* acked segments the server had lost, queued again */
    unsigned released;   /* sessions whose audio the server released and we deleted */
    unsigned release_refused; /* released by the server, not complete here */
    unsigned release_withheld; /* released and complete here, but the server could not confirm it holds it */
    unsigned finishes_ok;
    unsigned sessions_seen;
    int last_http;
    bool compatible;
} api_status;

static char base[256];
static char credential[65];
static char installation[JOURNAL_UUID_CHARS];
static TaskHandle_t worker;
static api_status status;
/* Atomic mirrors for the display task. The full status struct belongs to the
 * API worker; exposing it directly would race while a settings page is drawn. */
static atomic_bool diagnostic_compatible;
static atomic_uint diagnostic_gate_ok, diagnostic_gate_failed;
/* Set only after a journaled queue/session state transition. The recorder task
 * consumes it as a request to verify the incremental RAM counters against the
 * complete journals after this synchronization pass. */
static bool local_queue_state_changed;
/* `limits.dashboard_cache_max_age_seconds` as the server last stated it, or 0
 * for a server that stated nothing. The panel gets its own copy for the staleness
 * mark; this one sets how often the worker goes and fetches a fresh snapshot. */
static unsigned cache_max_age_s;
/* A pending detail request. Written by the display task, read by the worker;
 * `pending` is the handover, so the strings are complete before it is set. */
static char entity_type[32], entity_id[40];
static atomic_bool entity_pending;
/* A task the detail view asked to mark complete. Distinct from entity_id/
 * entity_type: a fetch and a mutation in flight at once must not overwrite
 * each other's target. */
static char complete_task_id[40];
static atomic_bool complete_task_pending;
static atomic_bool history_pending;
static char session_id_wanted[40];
static atomic_bool session_pending;

/* A small durable desired-state queue for list items. Unlike the audio queue,
 * these records contain no user content, only opaque UUIDs and active/done.
 * `committed=0` is a draft while its list detail is open; leaving promotes all
 * drafts. Loading promotes them too, so a reset cannot silently discard a
 * visible check mark. NVS blobs span pages, and this fixed store stays below
 * four KiB while covering more items than one dashboard snapshot can expose. */
#define LIST_ACTIONS_MAGIC 0x4c534131u
#define LIST_ACTIONS_MAX 64
typedef struct {
    char id[37];
    uint8_t done;
    uint8_t committed;
} list_action;
typedef struct {
    uint32_t magic;
    uint16_t count;
    uint16_t reserved;
    list_action items[LIST_ACTIONS_MAX];
} list_action_store;
static list_action_store list_actions;
static SemaphoreHandle_t list_actions_lock;
static void publish_queue_status(void);

static bool list_actions_save_locked(void) {
    nvs_handle_t n;
    if (nvs_open("notebook", NVS_READWRITE, &n) != ESP_OK) return false;
    esp_err_t result = nvs_set_blob(n, "list_actions", &list_actions, sizeof(list_actions));
    if (result == ESP_OK) result = nvs_commit(n);
    nvs_close(n);
    if (result != ESP_OK) ESP_LOGW("api", "list action journal save failed: %s", esp_err_to_name(result));
    return result == ESP_OK;
}

static void list_actions_load(void) {
    list_actions_lock = xSemaphoreCreateMutex();
    memset(&list_actions, 0, sizeof(list_actions));
    list_actions.magic = LIST_ACTIONS_MAGIC;
    if (!list_actions_lock) return;
    nvs_handle_t n;
    size_t size = sizeof(list_actions);
    if (nvs_open("notebook", NVS_READONLY, &n) == ESP_OK) {
        if (nvs_get_blob(n, "list_actions", &list_actions, &size) != ESP_OK ||
            size != sizeof(list_actions) || list_actions.magic != LIST_ACTIONS_MAGIC ||
            list_actions.count > LIST_ACTIONS_MAX) {
            memset(&list_actions, 0, sizeof(list_actions));
            list_actions.magic = LIST_ACTIONS_MAGIC;
        }
        nvs_close(n);
    }
    bool recovered = false;
    for (unsigned i = 0; i < list_actions.count; i++) {
        if (!list_actions.items[i].committed) {
            list_actions.items[i].committed = 1;
            recovered = true;
        }
    }
    if (recovered) {
        list_actions_save_locked();
        ESP_LOGI("api", "recovered %u staged list item action(s)", list_actions.count);
    }
}

static int list_action_find_locked(const char *id) {
    for (unsigned i = 0; i < list_actions.count; i++)
        if (strcmp(list_actions.items[i].id, id) == 0) return (int)i;
    return -1;
}

static unsigned list_action_count(bool committed_only) {
    if (!list_actions_lock || xSemaphoreTake(list_actions_lock, pdMS_TO_TICKS(200)) != pdTRUE) return 0;
    unsigned count = 0;
    for (unsigned i = 0; i < list_actions.count; i++)
        if (!committed_only || list_actions.items[i].committed) count++;
    xSemaphoreGive(list_actions_lock);
    return count;
}

bool api_client_list_item_desired(const char *item_id, bool *done) {
    if (!item_id || !done || !list_actions_lock ||
        xSemaphoreTake(list_actions_lock, pdMS_TO_TICKS(200)) != pdTRUE) return false;
    int index = list_action_find_locked(item_id);
    if (index >= 0) *done = list_actions.items[index].done != 0;
    xSemaphoreGive(list_actions_lock);
    return index >= 0;
}

bool api_client_stage_list_item(const char *item_id, bool done) {
    if (!item_id || strlen(item_id) != 36 || !list_actions_lock ||
        xSemaphoreTake(list_actions_lock, pdMS_TO_TICKS(500)) != pdTRUE) return false;
    list_action_store *before = malloc(sizeof(*before));
    if (!before) { xSemaphoreGive(list_actions_lock); return false; }
    *before = list_actions;
    int index = list_action_find_locked(item_id);
    /* Every item in a fresh detail starts active. Reversing an unsent local
     * completion therefore removes the draft instead of queuing a no-op. */
    if (!done && index >= 0 && !list_actions.items[index].committed) {
        memmove(&list_actions.items[index], &list_actions.items[index + 1],
                (list_actions.count - (unsigned)index - 1) * sizeof(list_action));
        list_actions.count--;
    } else if (!done && index < 0) {
        free(before);
        xSemaphoreGive(list_actions_lock);
        return true;
    } else {
        if (index < 0) {
            if (list_actions.count >= LIST_ACTIONS_MAX) {
                free(before);
                xSemaphoreGive(list_actions_lock);
                ESP_LOGW("api", "list action journal full");
                return false;
            }
            index = (int)list_actions.count++;
            memset(&list_actions.items[index], 0, sizeof(list_action));
            snprintf(list_actions.items[index].id, sizeof(list_actions.items[index].id), "%s", item_id);
        }
        list_actions.items[index].done = done ? 1 : 0;
        list_actions.items[index].committed = 0;
    }
    bool saved = list_actions_save_locked();
    if (!saved) list_actions = *before;
    free(before);
    xSemaphoreGive(list_actions_lock);
    publish_queue_status();
    return saved;
}

bool api_client_commit_list_items(void) {
    if (!list_actions_lock || xSemaphoreTake(list_actions_lock, pdMS_TO_TICKS(500)) != pdTRUE) return false;
    bool changed = false;
    uint64_t promoted = 0;
    for (unsigned i = 0; i < list_actions.count; i++) {
        if (!list_actions.items[i].committed) {
            list_actions.items[i].committed = 1;
            promoted |= (uint64_t)1 << i;
            changed = true;
        }
    }
    if (changed && !list_actions_save_locked()) {
        for (unsigned i = 0; i < list_actions.count; i++)
            if (promoted & ((uint64_t)1 << i)) list_actions.items[i].committed = 0;
        changed = false;
    }
    xSemaphoreGive(list_actions_lock);
    publish_queue_status();
    if (changed && worker) xTaskNotifyGive(worker);
    return changed || promoted == 0;
}

static void auth_load(void) {
    nvs_handle_t n;if(nvs_open("notebook",NVS_READWRITE,&n)!=ESP_OK)return;
    size_t size=sizeof(installation);
    if(nvs_get_str(n,"install",installation,&size)!=ESP_OK){
        journal_uuid(installation,memo_queue_random);nvs_set_str(n,"install",installation);nvs_commit(n);
    }
    size=sizeof(credential);if(nvs_get_str(n,"credential",credential,&size)!=ESP_OK)credential[0]=0;
    nvs_close(n);
}

static void auth_header(esp_http_client_handle_t client) {
    if(!credential[0])return;
    char value[80];
    snprintf(value,sizeof(value),"Bearer %s",credential);
    esp_http_client_set_header(client,"Authorization",value);memset(value,0,sizeof(value));
}

static esp_err_t receive(esp_http_client_event_t *event) {
    response_buffer *response = event->user_data;
    if (event->event_id != HTTP_EVENT_ON_DATA || !event->data_len) return ESP_OK;
    if (response->used + (size_t)event->data_len >= response->capacity) {
        response->overflow = true;
        return ESP_FAIL;
    }
    memcpy(response->data + response->used, event->data, event->data_len);
    response->used += event->data_len;
    response->data[response->used] = 0;
    return ESP_OK;
}

/* One client for the worker's whole life, instead of one per request.
 *
 * A TLS connection is expensive to establish and cheap to keep: the handshake
 * verifies the certificate chain and agrees a key, several hundred milliseconds
 * of arithmetic, and it was being paid again for every single call. With one
 * handle the connection stays open across requests, so a pass over eight
 * sessions performs one handshake instead of sixteen. That is not only faster —
 * the arithmetic is the most power-hungry thing the device does outside
 * recording, and it was doing it dozens of times per sync.
 *
 * The buffer is static because the event handler is bound to it at creation
 * time and there is no way to change it afterwards. Safe: only the worker task
 * ever calls this. */
static esp_http_client_handle_t shared;
static response_buffer shared_response;

/* Anything a request may have left behind must go, or a GET would inherit the
 * body and content type of the POST before it. */
static void reset_request(esp_http_client_handle_t client, bool has_body) {
    if (has_body) esp_http_client_set_header(client, "Content-Type", "application/json");
    else {
        esp_http_client_delete_header(client, "Content-Type");
        esp_http_client_set_post_field(client, NULL, 0);
    }
}

static bool call(esp_http_client_method_t method, const char *path,
                 const char *request, char *body, size_t capacity, int *http) {
    char url[API_URL_MAX];
    int length = snprintf(url, sizeof(url), "%s%s", base, path);
    if (length <= 0 || length >= (int)sizeof(url)) return false;
    shared_response = (response_buffer){.data=body, .capacity=capacity};
    body[0] = 0;
    esp_http_client_config_t config = {
        .url = url,
        .method = method,
        .timeout_ms = 20000,
        .event_handler = receive,
        .user_data = &shared_response,
        .buffer_size = 1024,
        .buffer_size_tx = 1024,
        /* Verify the server against the built-in root store. Attached
         * unconditionally: it is ignored for http:// and cannot be forgotten
         * for https://, which is the direction the mistake would go. There is
         * deliberately no way to skip verification — a bearer credential and
         * recorded audio must never travel on an unverified connection, and a
         * switch for it would eventually be left on. */
        .crt_bundle_attach = esp_crt_bundle_attach,
        /* Together with the long-lived handle below, this is what actually
         * keeps the connection: the flag alone reuses nothing while a handle is
         * created and destroyed per request. */
        .keep_alive_enable = true,
    };
    bool first_use = !shared;
    if (!shared) {
        shared = esp_http_client_init(&config);
        if (!shared) return false;
        /* Set once: these headers belong to every request the device makes. */
        esp_http_client_set_header(shared, "Accept", "application/json");
        esp_http_client_set_header(shared, "X-Smart-Notebook-Contract", API_CONTRACT);
    } else if (esp_http_client_set_url(shared, url) != ESP_OK) {
        memset(url, 0, sizeof(url));
        return false;
    }
    esp_http_client_set_method(shared, method);
    /* Re-applied per request rather than once: the credential does not exist
     * yet when the first call goes out during enrollment. */
    auth_header(shared);
    reset_request(shared, request != NULL);
    if (request) esp_http_client_set_post_field(shared, request, strlen(request));

    esp_err_t result = esp_http_client_perform(shared);
    if (result != ESP_OK) {
        /* A broken connection must not be carried into the next request, and a
         * response the buffer could not hold leaves the stream at an unknown
         * position. Both are resolved by starting over. */
        bool was_reused = !first_use;
        esp_http_client_cleanup(shared);
        shared = NULL;
        /* One retry, and only on a connection we had inherited from an earlier
         * request. Keeping a connection open means the other end may close it
         * while nothing is happening — a proxy idle timeout is normal, not a
         * fault — and the device only finds out by trying. Reporting that as a
         * failed request would turn routine housekeeping into alarming log
         * lines and, worse, into a snapshot the panel never receives. A request
         * that fails on a freshly built connection is a real failure and is
         * reported as one. */
        if (was_reused && !shared_response.overflow) {
            ESP_LOGD("api", "connection was closed while idle; reconnecting");
            return call(method, path, request, body, capacity, http);
        }
        *http = 0;
        memset(url, 0, sizeof(url));
        return false;
    }
    *http = esp_http_client_get_status_code(shared);
    memset(url, 0, sizeof(url));
    return !shared_response.overflow;
}

static bool string_is(cJSON *object, const char *name, const char *expected) {
    cJSON *value = cJSON_GetObjectItemCaseSensitive(object, name);
    return cJSON_IsString(value) && strcmp(value->valuestring, expected) == 0;
}

static bool boolean_is(cJSON *object, const char *name, bool expected) {
    cJSON *value = cJSON_GetObjectItemCaseSensitive(object, name);
    return cJSON_IsBool(value) && cJSON_IsTrue(value) == expected;
}

/* A server that says nothing does not contradict us; see BACKEND_REQUIREMENTS.md
 * §1. Only a present, differing value is a conflict. */
static bool number_matches_or_absent(cJSON *object, const char *name, double expected) {
    cJSON *value = cJSON_GetObjectItemCaseSensitive(object, name);
    if (!cJSON_HasObjectItem(object, name)) return true;
    return cJSON_IsNumber(value) && value->valuedouble == expected;
}

/* `ErrorResponse` per contracts/client-openapi-v1.json: a flat top-level
 * object with `code`, not nested under an `error` key. */
static bool error_code_is(const char *text, const char *code) {
    cJSON *root = cJSON_Parse(text);
    bool match = cJSON_IsObject(root) && string_is(root, "code", code);
    cJSON_Delete(root);
    return match;
}

static bool response_retry_class_is(const char *text, const char *retry_class) {
    cJSON *root = cJSON_Parse(text);
    bool match = cJSON_IsObject(root) && string_is(root, "retry_class", retry_class);
    cJSON_Delete(root);
    return match;
}

/* A short chunk-attention reason from the error envelope. `credential_revoked`
 * is kept as the specific, already-documented word for the one code this
 * device treats by name; anything else falls back to the server's own `code`
 * verbatim (truncated to fit), since inventing a mapping for codes this
 * project has not seen would be exactly the kind of guessed backend semantics
 * CLAUDE.md rules out. */
static void reason_from_error_code(const char *text, char *out, size_t capacity) {
    if (error_code_is(text, "DEVICE_CREDENTIAL_REVOKED")) {
        snprintf(out, capacity, "credential_revoked");
        return;
    }
    cJSON *root = cJSON_Parse(text);
    cJSON *code = cJSON_GetObjectItemCaseSensitive(root, "code");
    if (cJSON_IsString(code)) snprintf(out, capacity, "%s", code->valuestring);
    else snprintf(out, capacity, "server_rejected");
    cJSON_Delete(root);
}

static bool server_available(cJSON *root) {
    return string_is(root, "status", "ready") || string_is(root, "status", "degraded");
}

static bool validate_capabilities(const char *text) {
    cJSON *root = cJSON_Parse(text);
    cJSON *contract = cJSON_GetObjectItemCaseSensitive(root, "contract");
    cJSON *features = cJSON_GetObjectItemCaseSensitive(root, "features");
    cJSON *profiles = cJSON_GetObjectItemCaseSensitive(root, "audio_profiles");
    cJSON *limits = cJSON_GetObjectItemCaseSensitive(root, "limits");
    cJSON *profile = cJSON_IsArray(profiles) ? cJSON_GetArrayItem(profiles, 0) : NULL;
    bool valid = cJSON_IsObject(root) && server_available(root) &&
        cJSON_IsObject(contract) && string_is(contract, "current", API_CONTRACT) &&
        cJSON_IsObject(features) && boolean_is(features, "audio_upload", true) &&
        boolean_is(features, "session_recovery", true) &&
        cJSON_IsObject(profile) && string_is(profile, "mime_type", "audio/mp4") &&
        string_is(profile, "container", "mp4") && string_is(profile, "codec", "aac-lc") &&
        cJSON_GetNumberValue(cJSON_GetObjectItemCaseSensitive(profile, "sample_rate_hz")) == 48000 &&
        cJSON_GetNumberValue(cJSON_GetObjectItemCaseSensitive(profile, "channels")) == 1 &&
        cJSON_GetNumberValue(cJSON_GetObjectItemCaseSensitive(profile, "max_chunk_bytes")) > 0 &&
        cJSON_IsObject(limits) &&
        cJSON_GetNumberValue(cJSON_GetObjectItemCaseSensitive(limits, "request_timeout_seconds")) > 0;
    /* Not part of the gate: a server that states no cache limit is still a
     * valid server, the device just falls back to its own. Anything absent,
     * negative or absurdly large counts as unstated rather than being clamped,
     * so a malformed value cannot silently shorten the window. */
    if (valid) {
        double max_age = cJSON_GetNumberValue(
            cJSON_GetObjectItemCaseSensitive(limits, "dashboard_cache_max_age_seconds"));
        cache_max_age_s = max_age > 0 && max_age < 604800 ? (unsigned)max_age : 0;
        screen_snapshot_cache_limit(cache_max_age_s);
    }
    cJSON_Delete(root);
    return valid;
}

static bool gate(const char *path) {
    char *body = malloc(API_RESPONSE_MAX);
    if (!body) return false;
    int http = 0;
    bool ok = call(HTTP_METHOD_GET, path, NULL, body, API_RESPONSE_MAX, &http) &&
              http == 200 && validate_capabilities(body);
    status.last_http = http;
    memset(body, 0, API_RESPONSE_MAX);
    free(body);
    return ok;
}

static bool enroll_if_needed(void) {
    if(credential[0])return true;
    nvs_handle_t n;if(nvs_open("notebook",NVS_READWRITE,&n)!=ESP_OK)return false;
    char code[201]={0};size_t size=sizeof(code);
    if(nvs_get_str(n,"enroll",code,&size)!=ESP_OK){nvs_close(n);return true;}
    cJSON *request=cJSON_CreateObject();cJSON_AddStringToObject(request,"enrollment_code",code);
    cJSON_AddStringToObject(request,"client_installation_id",installation);
    cJSON_AddStringToObject(request,"device_model","waveshare-esp32-s3-epaper-3.97");
    cJSON_AddStringToObject(request,"firmware_version",MEMO_FIRMWARE);
    char *json=cJSON_PrintUnformatted(request);cJSON_Delete(request);char *body=malloc(API_RESPONSE_MAX);int http=0;bool ok=false;
    if(json&&body&&call(HTTP_METHOD_POST,"/api/client/v1/installations/enroll",json,body,API_RESPONSE_MAX,&http)&&http==200){
        cJSON *root=cJSON_Parse(body);cJSON *token=cJSON_GetObjectItemCaseSensitive(root,"credential");
        if(cJSON_IsString(token)&&strlen(token->valuestring)==64){
            strcpy(credential,token->valuestring);
            esp_err_t saved=nvs_set_str(n,"credential",credential);
            esp_err_t erased=nvs_erase_key(n,"enroll");
            ok=saved==ESP_OK&&(erased==ESP_OK||erased==ESP_ERR_NVS_NOT_FOUND)&&nvs_commit(n)==ESP_OK;
        }cJSON_Delete(root);
    }
    if(json){memset(json,0,strlen(json));cJSON_free(json);}if(body){memset(body,0,API_RESPONSE_MAX);free(body);}memset(code,0,sizeof(code));nvs_close(n);status.last_http=http;
    return ok;
}

/* Latch the queue counts and let the panel redraw them. `screen_status` only
 * stores the values; a screen message is what actually paints them, so an
 * upload that empties the queue would otherwise leave a stale badge on the
 * panel until the next recording. */
static void publish_queue_status(void) {
    memo_queue_status queued = memo_queue_get();
    diagnostic_log_event(DIAG_EVENT_QUEUE, (int)queued.ready,
                         (int)queued.acked, (int)queued.attention);
    screen_status(queued.ready + list_action_count(false), queued.attention, queued.space_low);
    screen_status_storage_block(queued.space_block);
    if (!recorder_busy()) screen_memo(SCREEN_READY, 0);
}

static void fetch_dashboard(void) {
    char *body=malloc(API_RESPONSE_MAX);int http=0;
    if(!body){ESP_LOGW("dashboard","no memory for the response");return;}
    /* Every other fetch says what happened; this one only ever spoke when the
     * request had already succeeded. A failed call or a non-200 left no trace
     * at all, which is why an empty panel could not be told apart from a panel
     * nobody had tried to fill. */
    bool reached=call(HTTP_METHOD_GET,"/api/client/v1/dashboard?surface=esp32_epaper",NULL,body,API_RESPONSE_MAX,&http);
    status.last_http=http;
    /* `reached=0` together with `http=200` is not a contradiction and cost an
     * hour on 6 September: the server answered, and the transfer then failed on
     * this side. The overwhelmingly likely cause is the response outgrowing
     * API_RESPONSE_MAX — the event handler returns ESP_FAIL on overflow, which
     * aborts the perform after the status line has already been read. The same
     * limit already broke the session list at 24 entries. So the overflow is
     * named outright instead of leaving two numbers that look impossible. */
    if(!reached||http!=200)
        ESP_LOGW("dashboard","snapshot fetch failed: reached=%d http=%d overflow=%d limit=%d",
                 reached?1:0,http,shared_response.overflow?1:0,API_RESPONSE_MAX);
    if(reached&&http==200){
        cJSON *root=cJSON_Parse(body);cJSON *schema=cJSON_GetObjectItemCaseSensitive(root,"schema_version");
        cJSON *sections=cJSON_GetObjectItemCaseSensitive(root,"sections");
        if(cJSON_IsString(schema)&&strcmp(schema->valuestring,"1")==0&&cJSON_IsArray(sections)){
            ESP_LOGI("dashboard","snapshot accepted: sections=%d",cJSON_GetArraySize(sections));
            screen_snapshot_received(body, cJSON_GetArraySize(sections) == 0);
            /* Recording is local truth and owns the panel while it runs. A
             * snapshot that arrives mid-recording is accepted but not drawn;
             * the recorder returns to READY itself when the memo is stored. */
            if(recorder_busy()) ESP_LOGI("dashboard","render deferred: recording active");
            else screen_show(SCREEN_READY,NULL);
        } else ESP_LOGW("dashboard","snapshot rejected");
        cJSON_Delete(root);
    }
    memset(body,0,API_RESPONSE_MAX);free(body);
}

static bool response_matches_session(const char *text, const char *session_id) {
    cJSON *root = cJSON_Parse(text);
    cJSON *state = cJSON_GetObjectItemCaseSensitive(root, "state");
    bool valid = cJSON_IsObject(root) && string_is(root, "client_session_id", session_id) &&
        cJSON_IsString(state) && cJSON_HasObjectItem(root, "device_metadata") &&
        cJSON_HasObjectItem(root, "capture_mode") && cJSON_HasObjectItem(root, "created_at") &&
        cJSON_HasObjectItem(root, "updated_at") &&
        number_matches_or_absent(root, "sequence_base", JOURNAL_SEQUENCE_BASE);
    cJSON_Delete(root);
    return valid;
}

/* Persists the session-level defect flag, idempotently — a state that already
 * matches is not rewritten, or every failed pass would grow the journal. */
static bool mark_session(journal_session *session, bool attention, const char *reason) {
    if (session->create_attention == attention &&
        strcmp(session->create_reason, reason ? reason : "") == 0) return true;
    char payload[JOURNAL_MAX_PAYLOAD];
    int length = journal_build_session_state(payload, sizeof(payload), attention, reason);
    if (length <= 0 || !journal_append(session, payload, (size_t)length)) return false;
    memo_queue_note_session_transition(session->create_attention, attention);
    session->create_attention = attention;
    snprintf(session->create_reason, sizeof(session->create_reason), "%s", reason ? reason : "");
    local_queue_state_changed = true;
    return true;
}

static bool create_session(journal_session *session) {
    cJSON *request = cJSON_CreateObject();
    cJSON *metadata = cJSON_CreateObject();
    if (!request || !metadata) { cJSON_Delete(request); cJSON_Delete(metadata); return false; }
    cJSON_AddStringToObject(request, "client_session_id", session->session_id);
    cJSON_AddStringToObject(request, "capture_mode", session->capture_mode);
    cJSON_AddStringToObject(request, "source_type", "esp32_epaper_audio");
    /* Session identity per BACKEND_REQUIREMENTS.md §1: sequence_base is a
     * top-level field, immutable once the server has stored it. */
    cJSON_AddNumberToObject(request, "sequence_base", JOURNAL_SEQUENCE_BASE);
    cJSON_AddStringToObject(metadata, "client", "waveshare-esp32-s3-epaper-3.97");
    cJSON_AddStringToObject(metadata, "firmware_version", MEMO_FIRMWARE);
    cJSON_AddItemToObject(request, "device_metadata", metadata);
    char *json = cJSON_PrintUnformatted(request);
    cJSON_Delete(request);
    if (!json) return false;
    char *body = malloc(API_RESPONSE_MAX);
    if (!body) { cJSON_free(json); return false; }
    int http = 0;
    bool reached = call(HTTP_METHOD_POST, "/api/client/v1/sessions", json,
                        body, API_RESPONSE_MAX, &http);
    bool ok = reached && http == 201 && response_matches_session(body, session->session_id);
    status.last_http = http;
    /* Mark only on a definitive answer from the server, never on a transport
     * failure — a DNS or connectivity gap must not light this up, or it would
     * flag exactly the sessions that will succeed on the next retry. */
    if (reached && !ok) {
        char reason[24];
        if (http == 201) snprintf(reason, sizeof(reason), "response_mismatch");
        else snprintf(reason, sizeof(reason), "create_http_%d", http);
        mark_session(session, true, reason);
    } else if (ok && session->create_attention) {
        mark_session(session, false, "");
    }
    memset(json, 0, strlen(json));
    cJSON_free(json);
    memset(body, 0, API_RESPONSE_MAX);
    free(body);
    return ok;
}

static bool mark_chunk(journal_session *session, journal_chunk *chunk,
                       chunk_state state, const char *reason) {
    char payload[JOURNAL_MAX_PAYLOAD];
    int length = journal_build_chunk_state(payload, sizeof(payload), chunk->sequence, state, reason);
    if (length <= 0 || !journal_append(session, payload, (size_t)length)) return false;
    /* The card is written first and the counters follow, both here and nowhere
     * else. A state that did not reach the journal is not counted, and a state
     * that did is counted exactly once — including the departure from whatever
     * the segment was before. */
    memo_queue_note_transition(chunk->state, state);
    chunk->state = state;
    local_queue_state_changed = true;
    return true;
}

static bool ack_matches(const char *text, const journal_session *session,
                        const journal_chunk *chunk) {
    cJSON *root = cJSON_Parse(text);
    cJSON *remote = cJSON_GetObjectItemCaseSensitive(root, "chunk");
    bool valid = cJSON_IsObject(root) && boolean_is(root, "durable_ack", true) &&
        string_is(root, "client_session_id", session->session_id) && cJSON_IsObject(remote) &&
        string_is(remote, "client_chunk_id", chunk->chunk_id) &&
        string_is(remote, "content_hash", chunk->plain_sha256) &&
        cJSON_GetNumberValue(cJSON_GetObjectItemCaseSensitive(remote, "sequence")) == chunk->sequence &&
        cJSON_GetNumberValue(cJSON_GetObjectItemCaseSensitive(remote, "byte_length")) == chunk->plain_length;
    cJSON_Delete(root);
    return valid;
}

static bool stream_part(esp_http_client_handle_t client, const void *data, size_t length) {
    const char *cursor = data;
    while (length) {
        int written = esp_http_client_write(client, cursor, length);
        if (written <= 0) return false;
        cursor += written;
        length -= (size_t)written;
    }
    return true;
}

/* The uploader keeps its own connection, separate from the one the JSON calls
 * share, because a chunk is streamed with open/write rather than performed in
 * one go. Same reason, same gain: measured on the device, a memo of fourteen
 * segments spent 48 seconds uploading, of which roughly three seconds per
 * segment were the handshake alone. For the multi-hour mode in H5 — 360
 * segments in an hour — that difference is the whole feature. */
static esp_http_client_handle_t uploader;

static bool upload_attempt(const journal_session *session, const journal_chunk *chunk,
                           char *body, size_t capacity, int *http, bool *reused) {
    char path[128], url[API_URL_MAX], file_path[96], boundary[64], preamble[1400];
    snprintf(path, sizeof(path), "/api/client/v1/sessions/%s/audio-chunks", session->session_id);
    if (snprintf(url, sizeof(url), "%s%s", base, path) >= (int)sizeof(url)) return false;
    snprintf(file_path, sizeof(file_path), "%s/%s", session->directory, chunk->file);
    snprintf(boundary, sizeof(boundary), "sn-%s", chunk->chunk_id);
#define FIELD(name, format, value) "--%s\r\nContent-Disposition: form-data; name=\"" name "\"\r\n\r\n" format "\r\n"
    int prefix = snprintf(preamble, sizeof(preamble),
        FIELD("sequence", "%u", chunk->sequence)
        FIELD("client_chunk_id", "%s", chunk->chunk_id)
        FIELD("duration_ms", "%llu", (unsigned long long)chunk->duration_ms)
        FIELD("source_start_ms", "%llu", (unsigned long long)chunk->source_start_ms)
        FIELD("source_end_ms", "%llu", (unsigned long long)chunk->source_end_ms)
        FIELD("content_hash", "%s", chunk->plain_sha256)
        FIELD("codec", "%s", "aac-lc")
        FIELD("sample_rate_hz", "%u", 48000u)
        FIELD("channels", "%u", 1u)
        "--%s\r\nContent-Disposition: form-data; name=\"audio\"; filename=\"segment.m4a\"\r\nContent-Type: audio/mp4\r\n\r\n",
        boundary, chunk->sequence, boundary, chunk->chunk_id,
        boundary, (unsigned long long)chunk->duration_ms,
        boundary, (unsigned long long)chunk->source_start_ms,
        boundary, (unsigned long long)chunk->source_end_ms,
        boundary, chunk->plain_sha256, boundary, "aac-lc", boundary, 48000u,
        boundary, 1u, boundary);
#undef FIELD
    if (prefix <= 0 || prefix >= (int)sizeof(preamble)) return false;
    char ending[80];
    int suffix = snprintf(ending, sizeof(ending), "\r\n--%s--\r\n", boundary);
    if (suffix <= 0 || suffix >= (int)sizeof(ending)) return false;
    FILE *audio = fopen(file_path, "rb");
    if (!audio) return false;
    char content_type[96];
    snprintf(content_type, sizeof(content_type), "multipart/form-data; boundary=%s", boundary);
    esp_http_client_config_t config = {.url=url, .method=HTTP_METHOD_POST, .timeout_ms=20000,
        .buffer_size=1024, .buffer_size_tx=1024,
        /* The upload path carries the audio itself and needs the same root
         * store as every other request. Two client configurations is exactly
         * how one of them ends up without verification. */
        .crt_bundle_attach = esp_crt_bundle_attach,
        .keep_alive_enable = true};
    *reused = uploader != NULL;
    if (!uploader) {
        uploader = esp_http_client_init(&config);
        if (!uploader) { fclose(audio); return false; }
        esp_http_client_set_header(uploader, "Accept", "application/json");
        esp_http_client_set_header(uploader, "X-Smart-Notebook-Contract", API_CONTRACT);
    } else if (esp_http_client_set_url(uploader, url) != ESP_OK) {
        fclose(audio);
        esp_http_client_cleanup(uploader);
        uploader = NULL;
        return false;
    }
    esp_http_client_handle_t client = uploader;
    esp_http_client_set_method(client, HTTP_METHOD_POST);
    auth_header(client);
    /* The boundary is derived from the chunk id, so this header genuinely
     * changes per segment and must be set every time. */
    esp_http_client_set_header(client, "Content-Type", content_type);
    int64_t total = prefix + (int64_t)chunk->plain_length + suffix;
    bool ok = total <= INT_MAX && esp_http_client_open(client, (int)total) == ESP_OK &&
              stream_part(client, preamble, (size_t)prefix);
    uint8_t buffer[1024];
    uint64_t sent = 0;
    while (ok && sent < chunk->plain_length) {
        size_t wanted = chunk->plain_length - sent > sizeof(buffer) ? sizeof(buffer) : (size_t)(chunk->plain_length - sent);
        size_t got = fread(buffer, 1, wanted, audio);
        if (got != wanted || !stream_part(client, buffer, got)) ok = false;
        sent += got;
    }
    if (ok) ok = stream_part(client, ending, (size_t)suffix);
    fclose(audio);
    body[0] = 0;
    size_t used = 0;
    /* A connection may only be kept if the response was read to its end.
     * Stopping early leaves the rest of the body in the socket, and the next
     * request would read it as its own reply. */
    bool drained = false;
    if (ok && esp_http_client_fetch_headers(client) >= 0) {
        *http = esp_http_client_get_status_code(client);
        while (used + 1 < capacity) {
            int got = esp_http_client_read(client, body + used, capacity - used - 1);
            if (got < 0) { ok = false; break; }
            if (!got) { drained = true; break; }
            used += (size_t)got;
        }
        body[used] = 0;
    } else { *http = 0; ok = false; }
    if (!ok || !drained) {
        esp_http_client_cleanup(uploader);
        uploader = NULL;
    }
    memset(buffer, 0, sizeof(buffer));
    return ok && drained;
}

static bool upload_request(const journal_session *session, const journal_chunk *chunk,
                           char *body, size_t capacity, int *http) {
    bool reused = false;
    if (upload_attempt(session, chunk, body, capacity, http, &reused)) return true;
    /* Same reasoning as the JSON path: a connection the other side closed while
     * nothing was being uploaded is routine, and finding out costs one failed
     * attempt. Only a reused connection earns the second try — a failure on a
     * fresh one is a real failure and must be reported as such, or a genuinely
     * broken upload would retry forever without ever being counted. */
    if (!reused) return false;
    return upload_attempt(session, chunk, body, capacity, http, &reused);
}

static bool reconciliation_has(const journal_session *session, const journal_chunk *chunk) {
    char path[128];
    snprintf(path, sizeof(path), "/api/client/v1/sessions/%s/reconciliation", session->session_id);
    char *body = malloc(API_RESPONSE_MAX);
    if (!body) return false;
    int http = 0;
    bool found = false;
    if (call(HTTP_METHOD_GET, path, NULL, body, API_RESPONSE_MAX, &http) && http == 200) {
        cJSON *root = cJSON_Parse(body);
        cJSON *chunks = cJSON_GetObjectItemCaseSensitive(root, "chunks");
        cJSON *item;
        cJSON_ArrayForEach(item, chunks) {
            if (cJSON_GetNumberValue(cJSON_GetObjectItemCaseSensitive(item, "sequence")) == chunk->sequence &&
                string_is(item, "client_chunk_id", chunk->chunk_id) &&
                string_is(item, "content_hash", chunk->plain_sha256) &&
                boolean_is(item, "durable_ack", true)) { found = true; break; }
        }
        cJSON_Delete(root);
    }
    status.last_http = http;
    memset(body, 0, API_RESPONSE_MAX); free(body);
    return found;
}

static bool upload_chunk(journal_session *session, journal_chunk *chunk) {
    if (!mark_chunk(session, chunk, CHUNK_UPLOADING, "")) return false;
    char *body = malloc(API_RESPONSE_MAX);
    if (!body) { mark_chunk(session, chunk, CHUNK_READY, ""); return false; }
    int http = 0;
    bool request_ok = upload_request(session, chunk, body, API_RESPONSE_MAX, &http);
    bool durable = request_ok && http == 201 && ack_matches(body, session, chunk);
    /* retry_class immediate per API_INTERACTION.md's Segmentupload table: a
     * few tight, synchronous attempts, then fall through to the ordinary
     * ready-and-retry-next-pass cadence below — bounded, so a server that
     * keeps answering "immediate" is not hammered forever. */
    for (int attempt = 0; !durable && request_ok && http != 201 &&
         response_retry_class_is(body, "immediate") && attempt < 2; attempt++) {
        vTaskDelay(pdMS_TO_TICKS(500));
        request_ok = upload_request(session, chunk, body, API_RESPONSE_MAX, &http);
        durable = request_ok && http == 201 && ack_matches(body, session, chunk);
    }
    /* Reconciliation is a JSON request on the shared client. Do not keep the
     * upload TLS transport alive beside it after a failed upload: the ESP32-S3
     * has enough PSRAM for bodies, but certificate verification and TLS I/O
     * also need scarce internal heap. Two simultaneous TLS transports were
     * observed failing allocation while the ready journal itself stayed safe. */
    if (!durable && uploader) esp_http_client_close(uploader);
    if (!durable && reconciliation_has(session, chunk)) {
        durable = true;
        status.reconciled++;
    }
    status.last_http = http;
    bool persisted;
    if (durable) {
        persisted = mark_chunk(session, chunk, CHUNK_ACKED, "");
        if (persisted) status.uploads_acked++;
    } else if (http == 409) {
        persisted = mark_chunk(session, chunk, CHUNK_ATTENTION, "server_conflict");
        status.uploads_failed++;
    } else if (request_ok && (response_retry_class_is(body, "never") ||
                              response_retry_class_is(body, "user_action"))) {
        /* Stop and surface it instead of backing off forever. Local recording
         * and the rest of the queue are untouched; only this segment is
         * marked. */
        char reason[24];
        reason_from_error_code(body, reason, sizeof(reason));
        persisted = mark_chunk(session, chunk, CHUNK_ATTENTION, reason);
        status.uploads_failed++;
    } else {
        /* backoff, network, unclassified or unreadable: the conservative
         * default, retried on the next pass. Per-chunk backoff timing
         * distinct from the immediate loop above is not implemented — every
         * ready segment shares the same ~5 s retry cadence regardless of
         * retry_class here; see docs/CLIENT_SERVER_STATE.md. */
        persisted = mark_chunk(session, chunk, CHUNK_READY, "");
        status.uploads_failed++;
    }
    memset(body, 0, API_RESPONSE_MAX); free(body);
    return durable && persisted;
}

/* finish() answers 409 for more than one reason (client_sessions.py raises
 * the same SESSION_STATE_CONFLICT for "already aborted/completed" and for a
 * final_sequence mismatch), and the body's free-text message is not a wire
 * contract this device parses. Asking the session's own state directly is:
 * "completed"/"aborted" means the server already has what this finish was
 * trying to achieve, so the local side may as well agree. Anything else
 * (still processing, a real sequence conflict) is left alone to be retried
 * or surfaced as before. Without this a session whose finish the device
 * never durably learned about stays in the local queue and gets re-created
 * and re-finished on every single sync pass for the life of the card. */
static bool session_already_settled(const char *session_id) {
    char path[128];
    snprintf(path, sizeof(path), "/api/client/v1/sessions/%s", session_id);
    char *body = malloc(API_RESPONSE_MAX);
    if (!body) return false;
    int http = 0;
    bool ok = call(HTTP_METHOD_GET, path, NULL, body, API_RESPONSE_MAX, &http) && http == 200;
    bool settled = false;
    if (ok) {
        cJSON *root = cJSON_Parse(body);
        settled = cJSON_IsObject(root) &&
                  (string_is(root, "state", "completed") || string_is(root, "state", "aborted"));
        cJSON_Delete(root);
    }
    memset(body, 0, API_RESPONSE_MAX); free(body);
    return settled;
}

static bool finish_session(journal_session *session) {
    char path[128], request[128];
    snprintf(path, sizeof(path), "/api/client/v1/sessions/%s/finish", session->session_id);
    snprintf(request, sizeof(request), "{\"final_sequence\":%u,\"final_source_end_ms\":%llu}",
             session->final_sequence, (unsigned long long)session->final_source_end_ms);
    char *body = malloc(API_RESPONSE_MAX);
    if (!body) return false;
    int http = 0;
    bool ok = call(HTTP_METHOD_POST, path, request, body, API_RESPONSE_MAX, &http) && http == 200;
    if (ok) {
        cJSON *root = cJSON_Parse(body);
        cJSON *reconciliation = cJSON_GetObjectItemCaseSensitive(root, "reconciliation");
        ok = cJSON_IsObject(root) && cJSON_IsObject(reconciliation) &&
             string_is(reconciliation, "client_session_id", session->session_id) &&
             boolean_is(reconciliation, "upload_complete", true);
        cJSON_Delete(root);
    }
    status.last_http = http;
    memset(body, 0, API_RESPONSE_MAX); free(body);
    if (ok) { status.finishes_ok++; return true; }
    if (http == 409 && session_already_settled(session->session_id)) {
        ESP_LOGI("api", "finish %s: server already has it completed/aborted; settling locally",
                 session->session_id);
        return true;
    }
    return false;
}

/* The server accepted the finish but reports the upload as incomplete: it is
 * missing segments this device considers delivered.
 *
 * A durable ACK is a promise the server made. If the server later says it does
 * not have that segment, the promise did not survive on its side — a restored
 * backup, a wiped store, a lost write. The device still holds the audio, since
 * nothing is deleted before the retention policy allows it, so the honest
 * response is to send it again rather than to insist on an acknowledgement the
 * other side no longer honours. Without this the two sides deadlock silently:
 * the device never re-uploads because the segment is acked, the server never
 * completes because the segment is missing, and the session is re-created on
 * every sync forever.
 *
 * Only sequences the server explicitly lists as missing are demoted, and only
 * from ACKED — a segment in any other state is already on its way. Returns the
 * number reset, so the caller can tell "nothing to do" from "work scheduled". */
static unsigned resync_missing(journal_session *session) {
    char path[128];
    snprintf(path, sizeof(path), "/api/client/v1/sessions/%s/reconciliation", session->session_id);
    char *body = malloc(API_RESPONSE_MAX);
    if (!body) return 0;
    int http = 0;
    unsigned reset = 0, unavailable = 0;
    if (call(HTTP_METHOD_GET, path, NULL, body, API_RESPONSE_MAX, &http) && http == 200) {
        cJSON *root = cJSON_Parse(body);
        cJSON *missing = cJSON_GetObjectItemCaseSensitive(root, "missing_sequences");
        cJSON *item;
        cJSON_ArrayForEach(item, missing) {
            if (!cJSON_IsNumber(item)) continue;
            unsigned sequence = (unsigned)item->valuedouble;
            journal_chunk *chunk = journal_find(session, sequence);
            if (!chunk || chunk->state != CHUNK_ACKED) continue;
            /* Demotion only makes sense while the audio is still here to send.
             * Once the retention release has removed it, `ready` is a promise
             * the device cannot keep: the next boot finds no file and marks the
             * segment `attention`, turning a correctly delivered and released
             * recording into a permanent warning. That is what happened on
             * 6 September when the proxy was pointed at a backend that had never
             * seen these sessions — 66 segments, every one of them already
             * delivered and deliberately deleted. Kept acknowledged and counted
             * apart instead; the disagreement is real, but it is not this
             * device's to resolve by destroying its own history. */
            char audio[128];
            snprintf(audio, sizeof(audio), "%s/%08u.M4A", session->directory, chunk->sequence);
            struct stat info;
            if (stat(audio, &info) != 0) { unavailable++; continue; }
            if (!mark_chunk(session, chunk, CHUNK_READY, "server_missing")) break;
            reset++;
        }
        cJSON_Delete(root);
    }
    status.last_http = http;
    if (unavailable) {
        status.resync_impossible += unavailable;
        ESP_LOGW("api", "server missing %u acknowledged segments whose audio was already released; "
                        "kept acknowledged", unavailable);
    }
    if (reset) {
        status.resynced += reset;
        ESP_LOGW("api", "server missing %u acknowledged segments; queued again", reset);
    }
    memset(body, 0, API_RESPONSE_MAX); free(body);
    return reset;
}

static bool transfer_session(journal_session *session) {
    for (unsigned i = 0; i < session->chunk_count; i++) {
        journal_chunk *chunk = &session->chunks[i];
        if (chunk->state != CHUNK_READY) continue;
        if (recorder_busy() || !upload_chunk(session, chunk)) return false;
    }
    if (!session->finished) return true;
    for (unsigned i = 0; i < session->chunk_count; i++)
        if (session->chunks[i].state != CHUNK_ACKED) return false;
    if (finish_session(session)) return true;
    /* Everything is acknowledged locally, yet the finish did not complete. Ask
     * the server what it is actually missing; the next pass sends it. */
    resync_missing(session);
    return false;
}

static bool memo_name(const char *name) {
    return strlen(name) == 8 && strspn(name, "0123456789abcdefABCDEF") == 8;
}

/* One pass covers at most SESSION_WINDOW directories. The window start rotates
 * between passes, so a card holding more sessions than one pass can carry is
 * still covered completely instead of starving everything behind the first
 * SESSION_WINDOW entries. */
/* Bounded per pass, and the bound is about time, not memory: every request now
 * carries a TLS handshake of roughly three seconds, so a window of 32 sessions
 * meant a pass of several minutes. The window start rotates, so everything is
 * still covered — just spread over more passes, with the display responsive in
 * between. */
#define SESSION_WINDOW 8
static unsigned session_offset;

static bool selected_name(char names[][9], unsigned count, const char *name) {
    for (unsigned i = 0; i < count; i++)
        if (strcmp(names[i], name) == 0) return true;
    return false;
}

/* Delivery beats housekeeping. A rotating directory window kept old sessions
 * fair, but with 35 journals on the real card it also meant that a newly
 * recorded ready segment could miss the one wake-up caused by its recording
 * and wait several four-minute dashboard intervals. Replay local journals only
 * before the recorder queue's asynchronous boot rescan has necessarily
 * published its count, and put ready sessions first. No server state is
 * inferred; the rotating scan below still covers everything. */
static unsigned collect_ready_sessions(char names[][9], unsigned capacity) {
    if (recorder_busy()) return 0;
    DIR *directory = opendir(MEMO_ROOT);
    if (!directory) return 0;
    unsigned count = 0;
    struct dirent *entry;
    while (count < capacity && (entry = readdir(directory))) {
        if (!memo_name(entry->d_name)) continue;
        char path[64];
        snprintf(path, sizeof(path), "%s/%.8s", MEMO_ROOT, entry->d_name);
        journal_session *session = heap_caps_malloc(sizeof(journal_session), MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
        if (!session) break;
        journal_session_init(session, path);
        bool ready = journal_replay(session) && session->session_id[0] &&
                     journal_count_state(session, CHUNK_READY) > 0;
        free(session);
        if (!ready) continue;
        memcpy(names[count], entry->d_name, 8);
        names[count++][8] = 0;
    }
    closedir(directory);
    return count;
}

/* Sessions that are finished, whose every segment carries a persisted durable
 * ACK, and whose finish the server accepted in this boot. Without this the pass
 * re-created and re-finished every completed session on the card on every sync:
 * one POST per session per pass, growing with the recording history and
 * counting as a failure each time the server refused the repeat.
 *
 * Deliberately RAM only. Whether the server accepted the finish is not
 * persisted anywhere, and inventing a journal record for it would be inventing
 * backend semantics. After a restart every session is therefore offered once
 * more — idempotent on the server, bounded to a single pass, and the honest
 * behaviour when the device cannot know what the server has.
 *
 * Sized to the card, not to the window. It once held SESSION_WINDOW entries,
 * which looked reasonable and was not: the pass walks the card in a rotating
 * window of eight, so after the first eight sessions were marked the list was
 * full and every later session could never be marked at all. With 32 sessions on
 * the card that meant 24 of them were re-created and re-finished on every single
 * pass, forever — not once after a restart, as the note above claims. Sixty-four
 * entries cost about 2.4 KB and cover a realistic card. */
#define SETTLED_MAX 64
static char settled[SETTLED_MAX][JOURNAL_UUID_CHARS];
static unsigned settled_count;
static unsigned settled_next;   /* FIFO cursor once the list is full */

static bool is_settled(const char *session_id) {
    for (unsigned i = 0; i < settled_count; i++)
        if (strcmp(settled[i], session_id) == 0) return true;
    return false;
}

/* Bounded, and when full it evicts the oldest rather than refusing the newest.
 * Refusing was the worse of the two: it pinned the first eight sessions and left
 * every later one permanently unmarked, which is precisely the set the rotating
 * window keeps coming back to. A forgotten session costs one redundant pass; a
 * never-markable session costs one every pass for the life of the card. */
static void mark_settled(const char *session_id) {
    if (is_settled(session_id)) return;
    if (settled_count < SETTLED_MAX) {
        snprintf(settled[settled_count++], JOURNAL_UUID_CHARS, "%s", session_id);
        return;
    }
    snprintf(settled[settled_next], JOURNAL_UUID_CHARS, "%s", session_id);
    settled_next = (settled_next + 1) % SETTLED_MAX;
}

/* Nothing left to do: finished locally and every segment durably acknowledged.
 * A session that is merely finished still has segments to upload. */
static bool session_complete(const journal_session *session) {
    if (!session->finished) return false;
    for (unsigned i = 0; i < session->chunk_count; i++)
        if (session->chunks[i].state != CHUNK_ACKED) return false;
    return true;
}

/* --- local retention ------------------------------------------------------ */

/* True while any of this session's audio is still on the card. Once the files
 * are gone there is nothing to release, so the check costs no request. */
static bool audio_present(const journal_session *session) {
    for (unsigned i = 0; i < session->chunk_count; i++) {
        char path[96];
        struct stat info;
        snprintf(path, sizeof(path), "%s/%s", session->directory, session->chunks[i].file);
        if (stat(path, &info) == 0) return true;
    }
    return false;
}

/* Does the server itself say it holds every segment of this session?
 *
 * Answers only "yes" on an explicit, well-formed confirmation: HTTP 200, the
 * session named back, and `missing_sequences` present and empty. A malformed
 * body, an unreachable server, a missing field — all count as "no". The caller
 * uses this to gate deletion, so the safe answer must be the default one. */
static bool reconciliation_complete(const journal_session *session) {
    char path[128];
    snprintf(path, sizeof(path), "/api/client/v1/sessions/%s/reconciliation", session->session_id);
    char *body = malloc(API_RESPONSE_MAX);
    if (!body) return false;
    int http = 0;
    bool complete = false;
    if (call(HTTP_METHOD_GET, path, NULL, body, API_RESPONSE_MAX, &http) && http == 200) {
        cJSON *root = cJSON_Parse(body);
        cJSON *missing = cJSON_GetObjectItemCaseSensitive(root, "missing_sequences");
        complete = cJSON_IsObject(root) &&
                   string_is(root, "client_session_id", session->session_id) &&
                   cJSON_IsArray(missing) && cJSON_GetArraySize(missing) == 0;
        cJSON_Delete(root);
    }
    status.last_http = http;
    memset(body, 0, API_RESPONSE_MAX);
    free(body);
    return complete;
}

/* Ask the server whether it has durably processed and stored this recording.
 * `local_audio_release_allowed` is monotone and session-wide, and an absent
 * field counts as false — a server that says nothing has released nothing. */
static bool server_released(const journal_session *session) {
    char path[128];
    snprintf(path, sizeof(path), "/api/client/v1/sessions/%s", session->session_id);
    char *body = malloc(API_RESPONSE_MAX);
    if (!body) return false;
    int http = 0;
    bool allowed = false;
    if (call(HTTP_METHOD_GET, path, NULL, body, API_RESPONSE_MAX, &http) && http == 200) {
        cJSON *root = cJSON_Parse(body);
        allowed = cJSON_IsObject(root) &&
                  string_is(root, "client_session_id", session->session_id) &&
                  boolean_is(root, "local_audio_release_allowed", true);
        cJSON_Delete(root);
    }
    status.last_http = http;
    memset(body, 0, API_RESPONSE_MAX);
    free(body);
    return allowed;
}

/* The only place in the firmware that removes a user's recording.
 *
 * Two independent conditions, never one: the server has released the session,
 * and this device has itself confirmed that the session is closed and every
 * segment carries a persisted durable ACK. The server may release; it may not
 * order. A release for something that is not complete here is refused and made
 * visible as `attention` rather than obeyed — on 6 September this device held
 * valid ACKs for fourteen segments the server no longer had, and deleting on
 * the strength of the other side's word alone would have lost them.
 *
 * Only the audio goes. The journal and the session's state stay, or the next
 * scan would find an empty directory with no history. */
static void release_audio(journal_session *session) {
    if (!audio_present(session)) return;
    if (!server_released(session)) return;

    if (!session_complete(session)) {
        /* Not obeyed, and not silent either: the two sides disagree about a
         * recording, and that is exactly the state H1 requires to be visible. */
        ESP_LOGW("api", "server released a session this device has not completed");
        for (unsigned i = 0; i < session->chunk_count; i++) {
            journal_chunk *chunk = &session->chunks[i];
            if (chunk->state == CHUNK_ACKED) continue;
            mark_chunk(session, chunk, CHUNK_ATTENTION, "release_mismatch");
        }
        status.release_refused++;
        return;
    }

    /* Last check before the irreversible step, and deliberately a second
     * question to the server rather than a second look at our own records.
     *
     * Both conditions above are about what this device believes: our ACKs, our
     * finish. On 6 September that was not enough. Two sessions were uploaded,
     * acknowledged, released and deleted — and the very next reconciliation
     * reported both segments missing. The device had every local reason to
     * delete and destroyed recordings that had not survived on the other side.
     *
     * So immediately before deleting, ask the reconciliation endpoint what the
     * server actually holds. If it names any missing sequence, or the question
     * cannot be answered at all, nothing is deleted. Silence is not consent:
     * this is the one operation where an unreachable server must mean "keep". */
    if (!reconciliation_complete(session)) {
        ESP_LOGW("api", "release withheld: the server does not confirm holding every segment");
        status.release_withheld++;
        return;
    }

    unsigned removed = 0;
    for (unsigned i = 0; i < session->chunk_count; i++) {
        char path[96];
        snprintf(path, sizeof(path), "%s/%s", session->directory, session->chunks[i].file);
        if (unlink(path) == 0) removed++;
    }
    if (removed) {
        status.released++;
        memo_queue_update_space();
        /* Counted and logged, never quietly: deleting a recording is the one
         * irreversible thing this device does. */
        ESP_LOGI("api", "server released a session; %u audio files deleted", removed);
    }
}

static void create_local_sessions(void) {
    DIR *directory = opendir(MEMO_ROOT);
    if (!directory) return;
    char names[SESSION_WINDOW][9];
    unsigned count = collect_ready_sessions(names, SESSION_WINDOW);
    unsigned matching = 0, examined = 0;
    struct dirent *entry;
    while ((entry = readdir(directory))) {
        if (!memo_name(entry->d_name)) continue;
        unsigned index = matching++;
        if (index < session_offset || count == SESSION_WINDOW) continue;
        examined++;
        if (selected_name(names, count, entry->d_name)) continue;
        memcpy(names[count], entry->d_name, 8);
        names[count++][8] = 0;
    }
    closedir(directory);
    if (session_offset >= matching) session_offset = 0; /* Sessions vanished under the offset. */
    else if (matching > SESSION_WINDOW && examined) {
        session_offset = (session_offset + examined) % matching;
        ESP_LOGW("api", "session window: %u of %u sessions this pass; next start=%u",
                 count, matching, session_offset);
    } else session_offset = 0;
    status.sessions_seen = count;
    for (unsigned i = 0; i < count; i++) {
        char path[64];
        snprintf(path, sizeof(path), "%s/%s", MEMO_ROOT, names[i]);
        journal_session *session = heap_caps_malloc(sizeof(journal_session), MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
        if (!session) { status.replay_failed++; return; }
        journal_session_init(session, path);
        bool loaded = journal_replay(session) && session->session_id[0];
        if (!loaded) {
            /* Not a server problem: the directory holds no replayable journal,
             * or none that names a session. Counted apart so a card full of
             * pre-journal leftovers cannot look like a backend failure. */
            status.replay_failed++;
        } else if (is_settled(session->session_id)) {
            status.settled_skipped++;
            /* Settled means the server has the recording, not that it is done
             * with it. The release comes later, when its processing chain has
             * finished, so a settled session is exactly the one worth asking
             * about — and it costs nothing once the audio is gone. */
            release_audio(session);
        } else if (!recorder_busy() && !session->finished && session->chunk_count == 0) {
            /* A journal that names a session, holds no segment and has no end.
             * Nothing can ever change that: a new memo gets its own UUID and
             * writes its own directory, so this one will never gain a segment.
             *
             * It was still being offered on every pass, which created an empty
             * session on the server each time — idempotent, so it looked
             * harmless, but the server keeps it in `created` and the dashboard
             * lists it under open sessions. A recording that never happened
             * was showing up as a card, and since a session card now follows
             * its own action it was one press away from an empty view.
             *
             * Counted rather than skipped in silence: a state with no way out
             * is exactly the kind this device is supposed to name. The guard on
             * `recorder_busy` keeps the live session out of it — that one has
             * no segment yet either, and it is meant to be created early. */
            status.abandoned++;
        } else if (create_session(session)) {
            status.creates_ok++;
            bool has_ready = false;
            for (unsigned chunk = 0; chunk < session->chunk_count; chunk++)
                if (session->chunks[chunk].state == CHUNK_READY) { has_ready = true; break; }
            /* JSON and streaming use separate long-lived handles, but their
             * TLS transports must not stay open at once. Keep upload keepalive
             * across every chunk in this session, then release its transport
             * before finish/reconciliation returns to the JSON client. */
            if (has_ready && shared) esp_http_client_close(shared);
            bool transferred = transfer_session(session);
            if (has_ready && uploader) esp_http_client_close(uploader);
            if (transferred && session_complete(session))
                mark_settled(session->session_id);
            release_audio(session);
        } else {
            status.creates_failed++;
        }
        free(session);
        if (ulTaskNotifyTake(pdTRUE, 0)) break;
    }
}

static void fetch_entity(void) {
    if (!atomic_load(&entity_pending)) return;
    char path[128];
    snprintf(path, sizeof(path), "/api/client/v1/entities/%s/%s", entity_type, entity_id);
    char *body = malloc(API_RESPONSE_MAX);
    int http = 0;
    bool ok = body && call(HTTP_METHOD_GET, path, NULL, body, API_RESPONSE_MAX, &http) &&
              http == 200;
    if (ok) {
        /* The response must at least identify itself, or the detail view would
         * show whatever arrived. */
        cJSON *root = cJSON_Parse(body);
        ok = cJSON_IsObject(root) && string_is(root, "id", entity_id) &&
             string_is(root, "type", entity_type) &&
             cJSON_HasObjectItem(root, "status");
        cJSON_Delete(root);
    }
    status.last_http = http;
    screen_entity_received(ok ? body : NULL);
    ESP_LOGI("api", "entity fetch %s http=%d", ok ? "ok" : "failed", http);
    if (body) { memset(body, 0, API_RESPONSE_MAX); free(body); }
    atomic_store(&entity_pending, false);
}

/* The one mutation the closed action catalog grants the device today. The
 * response is the same DashboardEntityResponse a plain fetch returns (now
 * without `action`, the task being done), so it goes through the same
 * screen_entity_received() the detail view already redraws from — no second
 * "here is an updated task" path to keep in sync with the first. */
static void submit_complete_task(void) {
    if (!atomic_load(&complete_task_pending)) return;
    char path[128];
    snprintf(path, sizeof(path), "/api/client/v1/entities/task/%s/complete", complete_task_id);
    char *body = malloc(API_RESPONSE_MAX);
    int http = 0;
    /* No request body: the task is named in the path, and passing NULL rather
     * than "" is what actually signals "no body" to call() — reset_request()
     * decides on request != NULL, and an empty string is not NULL. */
    bool ok = body && call(HTTP_METHOD_POST, path, NULL, body, API_RESPONSE_MAX, &http) &&
              http == 200;
    if (ok) {
        cJSON *root = cJSON_Parse(body);
        ok = cJSON_IsObject(root) && string_is(root, "id", complete_task_id) &&
             string_is(root, "type", "task");
        cJSON_Delete(root);
    }
    status.last_http = http;
    if (ok) screen_entity_received(body);
    ESP_LOGI("api", "complete_task %s http=%d", ok ? "ok" : "failed", http);
    if (body) { memset(body, 0, API_RESPONSE_MAX); free(body); }
    atomic_store(&complete_task_pending, false);
}

/* Take a copy without holding the journal lock across an HTTP request. The
 * display may still revise the same item while the request is in flight; the
 * completion step below removes it only if the desired state still matches. */
static bool list_action_next(list_action *out) {
    if (!out || !list_actions_lock ||
        xSemaphoreTake(list_actions_lock, pdMS_TO_TICKS(200)) != pdTRUE) return false;
    bool found = false;
    for (unsigned i = 0; i < list_actions.count; i++) {
        if (list_actions.items[i].committed) {
            *out = list_actions.items[i];
            found = true;
            break;
        }
    }
    xSemaphoreGive(list_actions_lock);
    return found;
}

static void list_action_acked(const list_action *sent) {
    if (!sent || !list_actions_lock ||
        xSemaphoreTake(list_actions_lock, pdMS_TO_TICKS(500)) != pdTRUE) return;
    int index = list_action_find_locked(sent->id);
    if (index >= 0 && list_actions.items[index].committed &&
        list_actions.items[index].done == sent->done) {
        memmove(&list_actions.items[index], &list_actions.items[index + 1],
                (list_actions.count - (unsigned)index - 1) * sizeof(list_action));
        list_actions.count--;
        list_actions_save_locked();
    }
    xSemaphoreGive(list_actions_lock);
}

static void submit_list_actions(void) {
    list_action action;
    while (list_action_next(&action)) {
        char path[128], request[32];
        snprintf(path, sizeof(path), "/api/client/v1/entities/list-item/%s/status", action.id);
        snprintf(request, sizeof(request), "{\"status\":\"%s\"}", action.done ? "done" : "active");
        char *body = malloc(API_RESPONSE_MAX);
        int http = 0;
        bool ok = body && call(HTTP_METHOD_PUT, path, request, body, API_RESPONSE_MAX, &http) && http == 200;
        if (ok) {
            cJSON *root = cJSON_Parse(body);
            ok = cJSON_IsObject(root) && string_is(root, "id", action.id) &&
                 string_is(root, "status", action.done ? "done" : "active");
            cJSON_Delete(root);
        }
        status.last_http = http;
        ESP_LOGI("api", "list_item %s=%s http=%d", ok ? "ok" : "failed",
                 action.done ? "done" : "active", http);
        if (body) { memset(body, 0, API_RESPONSE_MAX); free(body); }
        if (!ok) break;
        list_action_acked(&action);
    }
}

/* The session list for the history view. Unlike the dashboard this is a plain
 * array, so the only check is that it is one: a body of the wrong shape is
 * reported as unavailable rather than drawn as an empty history, which would
 * claim there are no recordings. */
#define HISTORY_PAGE "12"

static void fetch_history(void) {
    if (!atomic_load(&history_pending)) return;
    char *body = malloc(API_RESPONSE_MAX);
    int http = 0;
    /* A window, not the whole list. Entries run to roughly 520 bytes, so an
     * unbounded history outgrows the receive buffer after a dozen recordings
     * and keeps growing for the life of the device — which is exactly how this
     * first showed up: 24 sessions came to 12 kB against an 8 kB buffer, and
     * the view said the history was unavailable. The number of visible entries
     * is a display decision and belongs here, not to the server. */
    bool ok = body && call(HTTP_METHOD_GET,
                           "/api/client/v1/sessions?limit=" HISTORY_PAGE, NULL,
                           body, API_RESPONSE_MAX, &http) && http == 200;
    if (ok) {
        cJSON *root = cJSON_Parse(body);
        ok = cJSON_IsArray(root);
        cJSON_Delete(root);
    }
    status.last_http = http;
    screen_history_received(ok ? body : NULL);
    /* http=200 with a failed fetch means the body did not fit or was not an
     * array; without that distinction an overflow reads like a server error. */
    ESP_LOGI("api", "history fetch %s http=%d", ok ? "ok" : "failed", http);
    if (body) { memset(body, 0, API_RESPONSE_MAX); free(body); }
    atomic_store(&history_pending, false);
}

/* The dashboard of one past recording. Same envelope as the home dashboard, so
 * the device renders it with the same code; the only check is the envelope
 * itself, exactly as for the home snapshot. */
static void fetch_session(void) {
    if (!atomic_load(&session_pending)) return;
    char path[128];
    snprintf(path, sizeof(path), "/api/client/v1/sessions/%s/dashboard?surface=esp32_epaper",
             session_id_wanted);
    char *body = malloc(API_RESPONSE_MAX);
    int http = 0;
    bool ok = body && call(HTTP_METHOD_GET, path, NULL, body, API_RESPONSE_MAX, &http) &&
              http == 200;
    if (ok) {
        cJSON *root = cJSON_Parse(body);
        cJSON *sections = cJSON_GetObjectItemCaseSensitive(root, "sections");
        ok = cJSON_IsObject(root) && string_is(root, "schema_version", "1") &&
             cJSON_IsArray(sections);
        cJSON_Delete(root);
    }
    status.last_http = http;
    screen_session_received(ok ? body : NULL);
    ESP_LOGI("api", "session dashboard %s http=%d", ok ? "ok" : "failed", http);
    if (body) { memset(body, 0, API_RESPONSE_MAX); free(body); }
    atomic_store(&session_pending, false);
}

static void synchronize(void) {
    status.compatible = false;
    atomic_store(&diagnostic_compatible, false);
    if(!enroll_if_needed()){ESP_LOGW("api","device enrollment pending; http=%d",status.last_http);return;}
    if (!gate("/api/client/capabilities") || !gate("/api/client/v1/contract")) {
        status.gates_failed++;
        atomic_fetch_add(&diagnostic_gate_failed, 1);
        diagnostic_log_event(DIAG_EVENT_GATE_FAILED, status.last_http, 0, 0);
        ESP_LOGW("api", "contract gate failed; http=%d", status.last_http);
        return;
    }
    status.compatible = true;
    status.gates_ok++;
    atomic_store(&diagnostic_compatible, true);
    atomic_fetch_add(&diagnostic_gate_ok, 1);
    diagnostic_log_event(DIAG_EVENT_GATE_OK, status.last_http, 0, 0);
    /* Apply queued list mutations before fetching the dashboard. A successful
     * check therefore disappears from both the following list detail and the
     * overview snapshot in the same synchronization pass. */
    submit_list_actions();
    /* The dashboard comes first, before any housekeeping. What the user sees
     * must not wait behind the session sweep: over TLS a pass costs seconds per
     * request, and with a card full of recordings the panel stayed empty for
     * minutes while the device was busy re-offering sessions nobody was waiting
     * for. Housekeeping is the background job, not the display. */
    fetch_dashboard();
    /* Uploads change the local queue, so the ambient badges are latched before
     * anything is drawn again and pushed once per pass afterwards. The display
     * task drops an identical frame, so an unchanged queue costs no refresh. */
    publish_queue_status();
    local_queue_state_changed = false;
    create_local_sessions();
    if (local_queue_state_changed) recorder_request_queue_rescan();
    else publish_queue_status();
    ESP_LOGI("api", "sync complete: compatible=1 sessions=%u create_ok=%u create_failed=%u replay_failed=%u settled=%u abandoned=%u acked=%u failed=%u resynced=%u unresyncable=%u released=%u refused=%u withheld=%u finish=%u",
             status.sessions_seen, status.creates_ok, status.creates_failed,
             status.replay_failed, status.settled_skipped, status.abandoned,
             status.uploads_acked, status.uploads_failed, status.resynced, status.resync_impossible,
             status.released, status.release_refused, status.release_withheld,
             status.finishes_ok);
}

/* Exponential backoff with jitter, bounded at both ends. The floor keeps a
 * single transient failure from costing minutes; the ceiling keeps a server that
 * is genuinely down from being asked every quarter minute for the rest of the
 * day. The jitter matters less on one device than it will on several, but it
 * costs nothing to spread the retries now rather than to remember later. */
static unsigned retry_delay_ms(unsigned failures) {
    unsigned span = API_RETRY_MIN_MS;
    for (unsigned i = 0; i < failures && span < API_RETRY_MAX_MS; i++) span *= 2;
    if (span > API_RETRY_MAX_MS) span = API_RETRY_MAX_MS;
    if (span <= API_RETRY_MIN_MS) return API_RETRY_MIN_MS;
    return API_RETRY_MIN_MS + esp_random() % (span - API_RETRY_MIN_MS + 1);
}

/* How long a healthy, idle device may go without asking for a new snapshot.
 *
 * Derived from what the server announces, with a local four-minute start ceiling.
 * Half the window, not all of it: refreshing exactly at the deadline would
 * mean the panel spends a moment showing something it has already declared
 * stale. Starting by four minutes leaves a full minute inside the five-minute
 * success target for DNS, TLS and response validation. */
static unsigned refresh_interval_s(void) {
    return dashboard_refresh_interval_s(cache_max_age_s);
}

/* Wake the radio for the duration of a pass and let it doze again afterwards.
 *
 * The default is WIFI_PS_MIN_MODEM, which nothing in this project ever chose —
 * it is simply what ESP-IDF starts with. The device log says what it costs:
 * `li: 4` against `DTIM period = 2`, so the station wakes every four beacons
 * while the access point announces buffered frames every two. A reply that
 * arrives in between can be missed. TCP retransmits through that; a name lookup,
 * one datagram each way on a short timeout, does not — which is why
 * `getaddrinfo() returns 202` kept appearing while an already open TLS
 * connection to the same host carried on working. The beacon timeouts and the
 * reset connections come from the same place.
 *
 * A pass lasts seconds and starts at most every four minutes when idle, so the saving is
 * kept where it is worth having and given up only where it costs reliability. */
static void radio_awake(bool awake) {
    esp_err_t result = esp_wifi_set_ps(awake ? WIFI_PS_NONE : WIFI_PS_MIN_MODEM);
    if (result != ESP_OK)
        ESP_LOGW("api", "power save change failed: %s", esp_err_to_name(result));
}

/* Resolve the server name once per pass, before anything else needs it.
 *
 * Two things are bought here. A lookup that fails is named as such instead of
 * hiding behind `http=0`, which stood equally for a dead name, a refused port
 * and a hung upstream. And the answer lands in lwIP's cache, so the requests
 * that follow in the same pass do not each pay their own lookup — on
 * 6 September three of them cost seven seconds apiece before the pass gave up.
 *
 * Deliberately not a cache of this device's own. The resolved address cannot go
 * into the URL without breaking certificate validation against the hostname,
 * and that check has no switch on this device by design. Caching therefore
 * belongs where it already is, in the resolver, and this only makes sure a
 * single transient miss does not fail the whole pass. */
static bool resolve_server(void) {
    const char *host = strstr(base, "://");
    host = host ? host + 3 : base;
    size_t length = strcspn(host, ":/");
    char name[128];
    if (!length || length >= sizeof(name)) return false;
    memcpy(name, host, length);
    name[length] = 0;
    struct addrinfo hints = {.ai_family = AF_INET, .ai_socktype = SOCK_STREAM};
    for (unsigned attempt = 0; attempt < 2; attempt++) {
        struct addrinfo *found = NULL;
        int failure = getaddrinfo(name, NULL, &hints, &found);
        if (found) freeaddrinfo(found);
        if (!failure) {
            if (attempt) ESP_LOGI("api", "name resolved on the second attempt");
            return true;
        }
        vTaskDelay(pdMS_TO_TICKS(400));
    }
    ESP_LOGW("api", "cannot resolve '%s'; the network is up but DNS is not answering", name);
    return false;
}

/* A pass that never reached the network still owes the display an answer. A
 * reader left pending keeps its "wird geladen …" placeholder on the panel and
 * keeps the worker on the five second tick, so the failure is delivered rather
 * than skipped. */
static void fail_pending_readers(void) {
    if (atomic_exchange(&entity_pending, false)) {
        screen_entity_received(NULL);
        ESP_LOGI("api", "entity fetch failed: name not resolved");
    }
    /* No screen_entity_received(NULL) here: a mutation that could not be
     * attempted must not blank the task the reader is still looking at, only
     * leave the button retriable. */
    if (atomic_exchange(&complete_task_pending, false))
        ESP_LOGI("api", "complete_task failed: name not resolved");
    if (atomic_exchange(&history_pending, false)) {
        screen_history_received(NULL);
        ESP_LOGI("api", "history fetch failed: name not resolved");
    }
    if (atomic_exchange(&session_pending, false)) {
        screen_session_received(NULL);
        ESP_LOGI("api", "session dashboard failed: name not resolved");
    }
}

static void api_task(void *unused) {
    (void)unused;
    /* The delay is drawn once, when the failure happens, and kept until it is
     * used. Drawing it again at the top of the loop would make the number in the
     * log a different one from the number actually waited. */
    unsigned failures = 0, retry_ms = 0;
    while (true) {
        /* A failed request leaves its chunk READY.  Keep a bounded retry clock
         * while work exists, so a transient server failure cannot strand the
         * queue until another recording or WLAN reconnect happens. */
        memo_queue_status queued = memo_queue_get();
        TickType_t wait;
        if (queued.ready || list_action_count(true) || atomic_load(&entity_pending) ||
            atomic_load(&history_pending) || atomic_load(&session_pending))
            wait = pdMS_TO_TICKS(5000);
        else if (retry_ms)
            wait = pdMS_TO_TICKS(retry_ms);
        else
            wait = pdMS_TO_TICKS(refresh_interval_s() * 1000);
        ulTaskNotifyTake(pdTRUE, wait);
        wifi_ap_record_t station;
        /* No association: nothing to try, and the failure count is left alone.
         * Going offline is not the server's fault and must not lengthen the
         * backoff that applies once the network is back. `IP_EVENT_STA_GOT_IP`
         * wakes the worker either way. */
        if (esp_wifi_sta_get_ap_info(&station) != ESP_OK) continue;
        radio_awake(true);
        if (resolve_server()) {
            /* A waiting reader comes before housekeeping. */
            fetch_entity();
            submit_complete_task();
            fetch_history();
            fetch_session();
            synchronize();
        } else {
            fail_pending_readers();
            /* Without a name nothing on this path can succeed, and every
             * request would otherwise pay its own lookup timeout. Marked as a
             * failed pass so the backoff applies rather than the previous
             * pass's success carrying over. */
            status.compatible = false;
        }
        radio_awake(false);
        /* `compatible` is the honest signal here: `synchronize` clears it on
         * entry and only sets it once enrollment and both gates have passed, so
         * it covers the unreachable server, the unredeemed enrollment code and
         * the incompatible contract alike. A dashboard that was merely too large
         * does not count as a failure — the server is fine and asking again in
         * fifteen seconds would not make the response any smaller. */
        if (status.compatible) { failures = 0; retry_ms = 0; }
        else {
            if (failures < 16) failures++;
            retry_ms = retry_delay_ms(failures);
            ESP_LOGW("api", "sync failed (%u in a row); next attempt in %u s",
                     failures, retry_ms / 1000);
        }
    }
}

void api_client_start(const char *base_url) {
    if (!base_url || !base_url[0] || worker) return;
    snprintf(base, sizeof(base), "%s", base_url);
    /* Said once at startup, and it names what is exposed rather than only
     * that the connection is insecure. The plain path stays usable on
     * purpose — it is the development profile — but it should never be
     * running unnoticed. */
    if (strncmp(base, "https://", 8) != 0)
        ESP_LOGW("api", "development profile: plain HTTP, credential and "
                        "audio travel unencrypted");
    auth_load();
    list_actions_load();
    while (strlen(base) && base[strlen(base)-1] == '/') base[strlen(base)-1] = 0;
    /* Priority 1, below the display task and level with the input loop in
     * app_main. It used to be 3, which put background housekeeping above the
     * user interface: a TLS handshake computes for hundreds of milliseconds
     * without ever blocking, so while it ran the button polling simply did not
     * get scheduled and presses were missed outright — no reaction, and nothing
     * in the log, because the press was never sampled. Uploading is the job
     * that may wait; the person pressing a button is not. */
    if (xTaskCreate(api_task, "api", 12288, NULL, 1, &worker) != pdPASS) {
        worker = NULL;
        ESP_LOGE("api", "worker allocation failed");
    }
}

void api_client_open_entity(const char *type, const char *id) {
    if (!type || !id || atomic_load(&entity_pending)) return;
    snprintf(entity_type, sizeof(entity_type), "%s", type);
    snprintf(entity_id, sizeof(entity_id), "%s", id);
    atomic_store(&entity_pending, true);
    if (worker) xTaskNotifyGive(worker);
}

void api_client_complete_task(const char *task_id) {
    if (!task_id || atomic_load(&complete_task_pending)) return;
    snprintf(complete_task_id, sizeof(complete_task_id), "%s", task_id);
    atomic_store(&complete_task_pending, true);
    if (worker) xTaskNotifyGive(worker);
}

void api_client_open_history(void) {
    if (atomic_load(&history_pending)) return;
    atomic_store(&history_pending, true);
    if (worker) xTaskNotifyGive(worker);
}

void api_client_open_session(const char *session_id) {
    if (!session_id || !session_id[0] || atomic_load(&session_pending)) return;
    snprintf(session_id_wanted, sizeof(session_id_wanted), "%s", session_id);
    atomic_store(&session_pending, true);
    if (worker) xTaskNotifyGive(worker);
}

api_client_diagnostic api_client_get_diagnostic(void) {
    return (api_client_diagnostic){
        .configured = base[0] != 0,
        .authenticated = credential[0] != 0,
        .compatible = atomic_load(&diagnostic_compatible),
        .gate_ok = atomic_load(&diagnostic_gate_ok),
        .gate_failed = atomic_load(&diagnostic_gate_failed),
    };
}

void api_client_network_up(void) { if (worker) xTaskNotifyGive(worker); }
void api_client_queue_changed(void) { if (worker) xTaskNotifyGive(worker); }
void api_client_request_sync(void) { if (worker) xTaskNotifyGive(worker); }

void api_client_report(void) {
    printf("@API configured=%d authenticated=%d compatible=%d gate_ok=%u gate_failed=%u sessions=%u create_ok=%u create_failed=%u replay_failed=%u settled=%u abandoned=%u acked=%u upload_failed=%u reconciled=%u resynced=%u unresyncable=%u released=%u refused=%u withheld=%u finish=%u list_actions=%u last_http=%d\n",
           base[0] ? 1 : 0, credential[0] ? 1 : 0, status.compatible ? 1 : 0, status.gates_ok,
           status.gates_failed, status.sessions_seen, status.creates_ok,
           status.creates_failed, status.replay_failed, status.settled_skipped,
           status.abandoned, status.uploads_acked, status.uploads_failed,
           status.reconciled, status.resynced, status.resync_impossible, status.released,
           status.release_refused, status.release_withheld, status.finishes_ok, list_action_count(false),
           status.last_http);
}
