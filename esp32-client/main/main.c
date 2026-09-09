#include <stdio.h>
#include <stdbool.h>
#include <stdatomic.h>
#include <stdlib.h>
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "driver/gpio.h"
#include "esp_event.h"
#include "esp_http_server.h"
#include "esp_netif.h"
#include "esp_random.h"
#include "esp_system.h"
#include "esp_wifi.h"
#include "nvs_flash.h"
#include "nvs.h"
#include "cJSON.h"
#include "screen.h"
#include "icons.h"
#include "storage.h"
#include "recorder.h"
#include "api_client.h"
#include "clock.h"
#include "network_config.h"
#include "diagnostic_log.h"
#include <fcntl.h>
#include <unistd.h>
#include "driver/usb_serial_jtag.h"
#include "driver/usb_serial_jtag_vfs.h"

static const char initial_page[] =
"<!doctype html><html lang=de><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
"<title>Notebook einrichten</title><style>body{font:18px system-ui;max-width:420px;margin:40px auto;padding:20px;background:#f5f3ee}"
"input,button{box-sizing:border-box;width:100%;padding:12px;margin:8px 0 20px}button{background:#183e34;color:white;border:0}button.secondary{background:#666}label{display:block}</style>"
"<h1>Notebook einrichten</h1><p>Verbinde dein Notebook mit einem 2,4-GHz-WLAN.</p>"
"<form><label>WLAN-Name<input id=s maxlength=32 required></label><label>WLAN-Passwort<input id=p type=password maxlength=63 autocomplete=new-password></label>"
"<label>Serveradresse (optional)<input id=u type=url placeholder='http://192.168.1.100:8000' maxlength=255></label>"
"<label>Enrollment-Code (optional)<input id=e maxlength=200 autocomplete=off></label>"
"<p>Eine leere Serveradresse behaelt die bisherige Einstellung. HTTP ist fuer lokale Tests erlaubt.</p><button>Speichern</button><button class=secondary type=button id=c>Abbrechen und bisheriges WLAN verwenden</button></form><p id=r role=status></p>"
"<script>document.querySelector('form').onsubmit=async e=>{e.preventDefault();let b=document.querySelector('button');b.disabled=true;"
"try{let a=await fetch('/configure',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ssid:document.querySelector('#s').value,password:document.querySelector('#p').value,server:document.querySelector('#u').value,enrollment_code:document.querySelector('#e').value})});"
"document.querySelector('#r').textContent=await a.text()}catch(e){document.querySelector('#r').textContent='Verbindung unterbrochen. Bitte erneut versuchen.'}b.disabled=false};"
"document.querySelector('#c').onclick=async()=>{let r=document.querySelector('#r');try{let a=await fetch('/cancel',{method:'POST'});r.textContent=await a.text()}catch(e){r.textContent='Verbindung beendet. Das Notebook kehrt zum bisherigen WLAN zurueck.'}}</script></html>";

static const char add_network_page[] =
"<!doctype html><html lang=de><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
"<title>WLAN hinzufuegen</title><style>body{font:18px system-ui;max-width:420px;margin:40px auto;padding:20px;background:#f5f3ee}"
"input,button{box-sizing:border-box;width:100%;padding:12px;margin:8px 0 20px}button{background:#183e34;color:white;border:0}button.secondary{background:#666}label{display:block}</style>"
"<h1>WLAN hinzufuegen</h1><p>Fuege ein weiteres 2,4-GHz-WLAN hinzu. Bereits gespeicherte WLANs bleiben erhalten; das Notebook verwendet automatisch ein erreichbares Profil.</p>"
"<form><label>WLAN-Name<input id=s maxlength=32 required></label><label>WLAN-Passwort<input id=p type=password maxlength=63 autocomplete=new-password></label>"
"<button>WLAN hinzufuegen</button><button class=secondary type=button id=c>Abbrechen</button></form><p id=r role=status></p>"
"<script>document.querySelector('form').onsubmit=async e=>{e.preventDefault();let b=document.querySelector('button');b.disabled=true;"
"try{let a=await fetch('/configure',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ssid:document.querySelector('#s').value,password:document.querySelector('#p').value})});"
"document.querySelector('#r').textContent=await a.text()}catch(e){document.querySelector('#r').textContent='Verbindung unterbrochen. Bitte erneut versuchen.'}b.disabled=false};"
"document.querySelector('#c').onclick=async()=>{let r=document.querySelector('#r');try{let a=await fetch('/cancel',{method:'POST'});r.textContent=await a.text()}catch(e){r.textContent='Verbindung beendet. Das Notebook kehrt zum bisherigen WLAN zurueck.'}}</script></html>";

static httpd_handle_t portal_server;
static atomic_bool portal_cancel_requested, portal_saved_requested;
static bool portal_active;
static atomic_bool portal_cancellable;
static char portal_password[17];
static notebook_network_config network_configuration;
static unsigned active_network;
static atomic_bool station_has_ip;
/* Wi-Fi callbacks run in the shared event loop and therefore only publish a
 * tiny state edge. SD I/O for the durable diagnostic happens in app_main. */
static atomic_int wifi_diag_pending;

static esp_err_t root(httpd_req_t *r) {
    httpd_resp_set_type(r, "text/html; charset=utf-8");
    httpd_resp_set_hdr(r, "Cache-Control", "no-store");
    const char *body = atomic_load(&portal_cancellable)
        ? add_network_page : initial_page;
    return httpd_resp_send(r, body, HTTPD_RESP_USE_STRLEN);
}

static esp_err_t configure(httpd_req_t *r) {
    bool adding_network = atomic_load(&portal_cancellable);
    if (r->content_len == 0 || r->content_len >= 1024)
        return httpd_resp_send_err(r, HTTPD_400_BAD_REQUEST, "Ungueltige Eingabe.");
    char *body = calloc(1, r->content_len + 1);
    if (!body)
        return httpd_resp_send_err(r, HTTPD_500_INTERNAL_SERVER_ERROR,
                                   "Kein Speicher.");
    size_t used = 0;
    while (used < r->content_len) {
        int count = httpd_req_recv(r, body + used, r->content_len - used);
        if (count == HTTPD_SOCK_ERR_TIMEOUT) continue;
        if (count <= 0) {
            memset(body, 0, r->content_len + 1);
            free(body);
            return ESP_FAIL;
        }
        used += count;
    }
    body[used] = 0;
    cJSON *j = cJSON_Parse(body);
    cJSON *s = cJSON_GetObjectItemCaseSensitive(j, "ssid");
    cJSON *p = cJSON_GetObjectItemCaseSensitive(j, "password");
    cJSON *u = cJSON_GetObjectItemCaseSensitive(j, "server");
    cJSON *e = cJSON_GetObjectItemCaseSensitive(j, "enrollment_code");
    const char *server_url = cJSON_IsString(u) ? u->valuestring : "";
    const char *enrollment = cJSON_IsString(e) ? e->valuestring : "";
    bool valid = cJSON_IsString(s) && cJSON_IsString(p) &&
        (!u || cJSON_IsString(u)) && (!e || cJSON_IsString(e)) &&
        notebook_network_profile_valid(s->valuestring, p->valuestring) &&
        notebook_server_url_valid(server_url) && strlen(enrollment) <= 200;
    if (!valid) {
        cJSON_Delete(j);
        memset(body, 0, r->content_len + 1);
        free(body);
        return httpd_resp_send_err(r, HTTPD_400_BAD_REQUEST,
            "WLAN ungueltig. Passwort leer lassen oder mindestens acht Zeichen verwenden; Serveradressen muessen HTTP/HTTPS nutzen.");
    }
    esp_err_t err = notebook_network_config_store(s->valuestring,
        p->valuestring, server_url, enrollment);
    cJSON_Delete(j);
    memset(body, 0, r->content_len + 1);
    free(body);
    if (err != ESP_OK) return httpd_resp_send_err(r, HTTPD_500_INTERNAL_SERVER_ERROR, "Speichern fehlgeschlagen.");
    screen_show(SCREEN_SAVED, NULL);
    atomic_store(&portal_saved_requested, true);
    httpd_resp_set_type(r, "text/plain; charset=utf-8");
    return httpd_resp_sendstr(r, adding_network
        ? "WLAN hinzugefuegt. Das Notebook versucht jetzt automatisch ein erreichbares gespeichertes Profil."
        : "Gespeichert. Das Geraet startet neu und versucht die neue WLAN-Konfiguration.");
}

static esp_err_t cancel_portal(httpd_req_t *r) {
    httpd_resp_set_type(r, "text/plain; charset=utf-8");
    if (!atomic_load(&portal_cancellable)) {
        httpd_resp_set_status(r, "409 Conflict");
        return httpd_resp_sendstr(r,
            "Abbrechen ist ohne ein bereits gespeichertes WLAN nicht moeglich.");
    }
    atomic_store(&portal_cancel_requested, true);
    return httpd_resp_sendstr(r,
        "Abgebrochen. Das bisherige Profil bleibt unveraendert.");
}

static void fill_station_config(wifi_config_t *config,
                                const notebook_network_profile *profile) {
    memset(config, 0, sizeof(*config));
    memcpy(config->sta.ssid, profile->ssid,
           strnlen(profile->ssid, sizeof(config->sta.ssid)));
    memcpy(config->sta.password, profile->password,
           strnlen(profile->password, sizeof(config->sta.password)));
    config->sta.scan_method = WIFI_ALL_CHANNEL_SCAN;
    config->sta.sort_method = WIFI_CONNECT_AP_BY_SIGNAL;
}

static esp_err_t select_network(unsigned index, bool connect) {
    if (index >= network_configuration.network_count)
        return ESP_ERR_INVALID_ARG;
    wifi_config_t station = {0};
    fill_station_config(&station, &network_configuration.networks[index]);
    esp_err_t err = esp_wifi_set_config(WIFI_IF_STA, &station);
    memset(&station, 0, sizeof(station));
    if (err == ESP_OK) active_network = index;
    if (err == ESP_OK && connect) err = esp_wifi_connect();
    return err;
}

static esp_err_t start_portal(bool cancellable, bool wifi_started) {
    if (portal_active) return ESP_OK;
    wifi_config_t access_point = {0};
    strcpy((char *)access_point.ap.ssid, "Notebook-Setup");
    snprintf(portal_password, sizeof(portal_password), "%08lx%08lx",
             (unsigned long)esp_random(), (unsigned long)esp_random());
    memcpy(access_point.ap.password, portal_password, sizeof(portal_password));
    access_point.ap.authmode = WIFI_AUTH_WPA2_PSK;
    access_point.ap.max_connection = 1;
    access_point.ap.channel = 1;
    esp_err_t err = esp_wifi_set_mode(cancellable ? WIFI_MODE_APSTA : WIFI_MODE_AP);
    if (err == ESP_OK) err = esp_wifi_set_config(WIFI_IF_AP, &access_point);
    if (err == ESP_OK && cancellable && !wifi_started)
        err = select_network(0, false);
    if (err == ESP_OK && !wifi_started) err = esp_wifi_start();
    memset(&access_point, 0, sizeof(access_point));
    if (err != ESP_OK) {
        memset(portal_password, 0, sizeof(portal_password));
        return err;
    }

    httpd_config_t http = HTTPD_DEFAULT_CONFIG();
    err = httpd_start(&portal_server, &http);
    if (err == ESP_OK) {
        httpd_uri_t get = {.uri="/", .method=HTTP_GET, .handler=root};
        httpd_uri_t post = {.uri="/configure", .method=HTTP_POST,
                            .handler=configure};
        httpd_uri_t cancel = {.uri="/cancel", .method=HTTP_POST,
                              .handler=cancel_portal};
        err = httpd_register_uri_handler(portal_server, &get);
        if (err == ESP_OK) err = httpd_register_uri_handler(portal_server, &post);
        if (err == ESP_OK) err = httpd_register_uri_handler(portal_server, &cancel);
    }
    if (err != ESP_OK) {
        if (portal_server) httpd_stop(portal_server);
        portal_server = NULL;
        if (cancellable) esp_wifi_set_mode(WIFI_MODE_STA);
        memset(portal_password, 0, sizeof(portal_password));
        return err;
    }
    portal_active = true;
    atomic_store(&portal_cancellable, cancellable);
    atomic_store(&portal_cancel_requested, false);
    atomic_store(&portal_saved_requested, false);
    diagnostic_log_event(DIAG_EVENT_SETUP_OPEN,
                         (int)network_configuration.network_count, 0, 0);
    printf("Einrichtung: Notebook-Setup / %s / http://192.168.4.1\n",
           portal_password);
    screen_show(cancellable ? SCREEN_SETUP_TEMP : SCREEN_SETUP,
                portal_password);
    return ESP_OK;
}

static void stop_temporary_portal(void) {
    if (!portal_active || !atomic_load(&portal_cancellable)) return;
    if (portal_server) httpd_stop(portal_server);
    portal_server = NULL;
    portal_active = false;
    atomic_store(&portal_cancellable, false);
    memset(portal_password, 0, sizeof(portal_password));
    esp_wifi_set_mode(WIFI_MODE_STA);
    if (!atomic_load(&station_has_ip)) select_network(active_network, true);
    screen_network_setup_end();
}

static bool clear_forced_setup(void) {
    nvs_handle_t n;
    esp_err_t err = nvs_open("notebook", NVS_READWRITE, &n);
    if (err == ESP_OK) {
        err = nvs_set_u8(n, "setup", 0);
        if (err == ESP_OK) err = nvs_commit(n);
        nvs_close(n);
    }
    return err == ESP_OK;
}

static void report_network_status(void) {
    notebook_network_config persisted = {0};
    notebook_network_config_load(&persisted);
    unsigned associated = 0;
    wifi_ap_record_t access_point = {0};
    if (esp_wifi_sta_get_ap_info(&access_point) == ESP_OK) {
        for (unsigned index = 0; index < network_configuration.network_count;
             index++) {
            if (strcmp((const char *)access_point.ssid,
                       network_configuration.networks[index].ssid) == 0) {
                associated = index + 1;
                break;
            }
        }
    }
    memset(&access_point, 0, sizeof(access_point));
    printf("@NETWORK ram_profiles=%u stored_profiles=%u selected=%u associated=%u portal=%u connected=%u\n",
           network_configuration.network_count, persisted.network_count,
           active_network + 1, associated, portal_active ? 1 : 0,
           atomic_load(&station_has_ip) ? 1 : 0);
    memset(&persisted, 0, sizeof(persisted));
}

static void wifi_event(void *arg, esp_event_base_t base, int32_t id, void *data) {
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) esp_wifi_connect();
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        atomic_store(&station_has_ip, false);
        atomic_store(&wifi_diag_pending, 1);
        printf("WLAN getrennt; erneuter Versuch.\n");
        screen_status_network(false);
        // Retry scheduling occurs in app_main, without blocking the event loop.
    }
    if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        atomic_store(&station_has_ip, true);
        atomic_store(&wifi_diag_pending, 2);
        printf("WLAN verbunden.\n");
        /* Which resolver the lease handed over. Missing from the log until now,
         * and it is exactly the fact a failing name lookup needs: whether the
         * device got a resolver at all, and whether it is the one meant to
         * answer. Without it, `cannot resolve …` says only that something is
         * wrong, not where. Addresses are not secrets and no name is printed. */
        ip_event_got_ip_t *event = data;
        esp_netif_dns_info_t dns;
        char text[40];
        if (event && esp_netif_get_dns_info(event->esp_netif, ESP_NETIF_DNS_MAIN, &dns) == ESP_OK)
            printf("DNS (primaer): %s\n", esp_ip4addr_ntoa(&dns.ip.u_addr.ip4, text, sizeof(text)));
        /* Two more resolvers behind the DHCP-provided one, not instead of it —
         * MAIN is left exactly as DHCP set it. The gateway often runs its own
         * caching resolver, distinct from whatever DNS option DHCP advertised;
         * 1.1.1.1 is a fixed, public last resort for a primary that stops
         * answering. Nothing here retries anything itself: LWIP's DNS client
         * already moves to the next configured server on a timeout on its own
         * (dns.c) once more than one slot is filled. Certificate validation
         * is unaffected either way — it checks the hostname, never which
         * resolver supplied the address for it. */
        if (event) {
            esp_netif_dns_info_t backup = {0};
            backup.ip.type = ESP_IPADDR_TYPE_V4;
            backup.ip.u_addr.ip4 = event->ip_info.gw;
            esp_netif_set_dns_info(event->esp_netif, ESP_NETIF_DNS_BACKUP, &backup);

            esp_netif_dns_info_t fallback = {0};
            fallback.ip.type = ESP_IPADDR_TYPE_V4;
            fallback.ip.u_addr.ip4.addr = 0x01010101; /* 1.1.1.1 — same bytes in either order */
            esp_netif_set_dns_info(event->esp_netif, ESP_NETIF_DNS_FALLBACK, &fallback);
        }
        if (event && esp_netif_get_dns_info(event->esp_netif, ESP_NETIF_DNS_BACKUP, &dns) == ESP_OK &&
            dns.ip.u_addr.ip4.addr)
            printf("DNS (zweiter): %s\n", esp_ip4addr_ntoa(&dns.ip.u_addr.ip4, text, sizeof(text)));
        if (event && esp_netif_get_dns_info(event->esp_netif, ESP_NETIF_DNS_FALLBACK, &dns) == ESP_OK &&
            dns.ip.u_addr.ip4.addr)
            printf("DNS (dritter): %s\n", esp_ip4addr_ntoa(&dns.ip.u_addr.ip4, text, sizeof(text)));
        screen_status_network(true);
        /* Every join, not only the first: a device that was off for a week has
         * a useless clock even though it once had a good one. */
        clock_network_up();
        api_client_network_up();
    }
}

static bool save_server(const char *url) {
    if (!url || strlen(url) > 255 ||
        (strncmp(url, "http://", 7) != 0 && strncmp(url, "https://", 8) != 0)) return false;
    char *stored=calloc(1,1024);
    if(!stored)return false;
    size_t length = 1024;
    nvs_handle_t n;
    if (nvs_open("notebook", NVS_READWRITE, &n) != ESP_OK) { free(stored); return false; }
    esp_err_t err = nvs_get_str(n, "config", stored, &length);
    cJSON *config = err == ESP_OK ? cJSON_Parse(stored) : NULL;
    if (!cJSON_IsObject(config)) { cJSON_Delete(config); nvs_close(n); free(stored); return false; }
    cJSON_DeleteItemFromObjectCaseSensitive(config, "server");
    cJSON_AddStringToObject(config, "server", url);
    char *encoded = cJSON_PrintUnformatted(config);
    cJSON_Delete(config);
    if (!encoded || strlen(encoded) >= 1024) err = ESP_ERR_INVALID_SIZE;
    else {
        err = nvs_set_str(n, "config", encoded);
        if (err == ESP_OK) err = nvs_commit(n);
    }
    if (encoded) { memset(encoded, 0, strlen(encoded)); cJSON_free(encoded); }
    memset(stored, 0, 1024);
    free(stored);
    nvs_close(n);
    return err == ESP_OK;
}

static bool save_enrollment(const char *code) {
    if(!code||strlen(code)<12||strlen(code)>200)return false;
    nvs_handle_t n;if(nvs_open("notebook",NVS_READWRITE,&n)!=ESP_OK)return false;
    esp_err_t err=nvs_set_str(n,"enroll",code);
    esp_err_t erased=nvs_erase_key(n,"credential");
    if(err==ESP_OK&&erased!=ESP_OK&&erased!=ESP_ERR_NVS_NOT_FOUND)err=erased;
    if(err==ESP_OK)err=nvs_commit(n);
    nvs_close(n);
    return err==ESP_OK;
}

void app_main(void) {
    usb_serial_jtag_driver_config_t usb_config = { .tx_buffer_size=1024, .rx_buffer_size=256 };
    ESP_ERROR_CHECK(usb_serial_jtag_driver_install(&usb_config));
    usb_serial_jtag_vfs_use_driver();
    ESP_ERROR_CHECK(nvs_flash_init()); // Never silently erase stored credentials.
    screen_start();
    screen_show(SCREEN_CONNECTING, NULL);
    gpio_set_direction(GPIO_NUM_0, GPIO_MODE_INPUT);
    gpio_set_pull_mode(GPIO_NUM_0, GPIO_PULLUP_ONLY);
    gpio_set_direction(GPIO_NUM_5, GPIO_MODE_INPUT);
    gpio_set_pull_mode(GPIO_NUM_5, GPIO_PULLUP_ONLY);
    gpio_set_direction(GPIO_NUM_4, GPIO_MODE_INPUT);
    gpio_set_pull_mode(GPIO_NUM_4, GPIO_PULLUP_ONLY);
    gpio_set_direction(GPIO_NUM_6, GPIO_MODE_INPUT);
    gpio_set_pull_mode(GPIO_NUM_6, GPIO_PULLUP_ONLY);
    nvs_handle_t n;
    uint8_t force_setup = 0;
    if (nvs_open("notebook", NVS_READONLY, &n) == ESP_OK) {
        nvs_get_u8(n, "setup", &force_setup);
        nvs_close(n);
    }
    bool have_network = notebook_network_config_load(&network_configuration);
    printf("@NETWORK loaded_profiles=%u\n", network_configuration.network_count);
    bool setup = !have_network || force_setup;
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    /* After esp_netif_init and not before: SNTP registers itself with the lwIP
     * task, and calling it earlier aborts on an invalid mailbox — a boot loop,
     * not a warning. Starting it here also covers the setup-portal case, where
     * it simply never synchronises because there is no upstream network. */
    clock_start();
    esp_netif_create_default_wifi_sta();
    esp_netif_create_default_wifi_ap();
    wifi_init_config_t init = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&init));
    ESP_ERROR_CHECK(esp_wifi_set_storage(WIFI_STORAGE_RAM));
    if (have_network) {
        ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT,
            ESP_EVENT_ANY_ID, wifi_event, NULL));
        ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT,
            IP_EVENT_STA_GOT_IP, wifi_event, NULL));
    }
    if (setup) {
        ESP_ERROR_CHECK(start_portal(have_network, false));
    } else {
        screen_show(SCREEN_CONNECTING, NULL);
        api_client_start(network_configuration.server);
        ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
        ESP_ERROR_CHECK(select_network(0, false));
        ESP_ERROR_CHECK(esp_wifi_start());
    }
    if(!setup) recorder_start();
    static char command[300]; size_t command_len=0;
    unsigned held = 0, ticks = 0, middle_ticks = 0;
    bool recording_gesture = false;
    /* Edge state of the two focus keys. They are read here and nowhere else, so
     * the previous level lives with the loop that samples it. */
    bool up_was_down = false, down_was_down = false;
    while (true) {
        vTaskDelay(pdMS_TO_TICKS(100));
        int wifi_edge = atomic_exchange(&wifi_diag_pending, 0);
        if (wifi_edge == 1)
            diagnostic_log_event(DIAG_EVENT_WIFI_DOWN, 0, 0, 0);
        else if (wifi_edge == 2)
            diagnostic_log_event(DIAG_EVENT_WIFI_UP, 0, 0, 0);
        if (!setup && screen_take_network_setup_request() &&
            !portal_active && !recorder_busy()) {
            esp_err_t err = start_portal(true, true);
            if (err != ESP_OK)
                printf("@SETUP start_failed=%s\n", esp_err_to_name(err));
        }
        if (atomic_exchange(&portal_cancel_requested, false)) {
            if (setup) {
                if (clear_forced_setup()) {
                    printf("@SETUP cancelled; restarting with saved profiles\n");
                    vTaskDelay(pdMS_TO_TICKS(100));
                    esp_restart();
                }
            } else {
                printf("@SETUP cancelled; keeping saved profiles\n");
                diagnostic_log_event(DIAG_EVENT_SETUP_CANCEL,
                    (int)network_configuration.network_count, 0, 0);
                stop_temporary_portal();
            }
        }
        if (atomic_exchange(&portal_saved_requested, false)) {
            /* Give the HTTP task time to finish the small acknowledgement. */
            vTaskDelay(pdMS_TO_TICKS(1000));
            if (setup) {
                printf("@SETUP saved; restarting initial setup\n");
                esp_restart();
            }
            stop_temporary_portal();
            notebook_network_config *loaded = calloc(1, sizeof(*loaded));
            if (!loaded || !notebook_network_config_load(loaded)) {
                printf("@SETUP saved_but_reload_failed\n");
                diagnostic_log_event(DIAG_EVENT_SETUP_SAVED,
                    (int)network_configuration.network_count, 0, 0);
            } else {
                memset(&network_configuration, 0, sizeof(network_configuration));
                memcpy(&network_configuration, loaded, sizeof(network_configuration));
                esp_wifi_disconnect();
                atomic_store(&station_has_ip, false);
                esp_err_t err = select_network(0, true);
                printf("@SETUP saved; profiles=%u live_switch=%s\n",
                       network_configuration.network_count,
                       esp_err_to_name(err));
                diagnostic_log_event(DIAG_EVENT_SETUP_SAVED,
                    (int)network_configuration.network_count,
                    err == ESP_OK ? 1 : 0, 0);
            }
            if (loaded) {
                memset(loaded, 0, sizeof(*loaded));
                free(loaded);
            }
        }
        char ch;
        while(usb_serial_jtag_read_bytes(&ch,1,0)>0) {
            if(ch=='\n' || ch=='\r') {
                command[command_len]=0;
                if(!setup && strcmp(command,"wifi-reconnect")==0) {
                    printf("DIAG: intentional WLAN disconnect; automatic retry follows.\n");
                    esp_wifi_disconnect();
                }
                if(!setup && strcmp(command,"memo-test")==0) recorder_test();
                if(!setup && strcmp(command,"memo-export")==0) recorder_export_test();
                if(!setup && strcmp(command,"memo-list")==0) recorder_files(NULL);
                if(!setup && strcmp(command,"queue-status")==0) recorder_queue_status();
                if(!setup && strcmp(command,"api-status")==0) api_client_report();
                if(!setup && strcmp(command,"network-status")==0)
                    report_network_status();
                if(!setup && strcmp(command,"diaglog-status")==0)
                    diagnostic_log_report();
                if(!setup && strncmp(command,"server-set ",11)==0) {
                    if (save_server(command+11)) {
                        printf("@SERVER saved; restarting\n");
                        vTaskDelay(pdMS_TO_TICKS(100));
                        esp_restart();
                    } else printf("@SERVER invalid_or_unsaved\n");
                }
                if(!setup && strncmp(command,"enroll-set ",11)==0) {
                    if(save_enrollment(command+11)) {
                        printf("@ENROLL saved; restarting\n");
                        vTaskDelay(pdMS_TO_TICKS(100));
                        esp_restart();
                    } else printf("@ENROLL invalid_or_unsaved\n");
                }
                /* Restart without unplugging anything. Refused during a
                 * recording: a reset mid-capture costs the segment being
                 * written, and no diagnostic convenience is worth that. A reset
                 * during an upload is safe by design — the segment falls back
                 * from `uploading` to `ready` and is sent again. */
                if(!setup && strcmp(command,"reboot")==0) {
                    if(recorder_busy()) printf("@REBOOT refused_recording\n");
                    else {
                        printf("@REBOOT restarting\n");
                        vTaskDelay(pdMS_TO_TICKS(100));
                        esp_restart();
                    }
                }
                if(!setup && strncmp(command,"memo-get ",9)==0) recorder_files(command+9);
                if(!setup && strncmp(command,"memo-why ",9)==0) recorder_explain(command+9);
                if(!setup && strncmp(command,"memo-discard ",13)==0) recorder_discard(command+13);
                /* The count is mandatory and is checked against the card, so a
                 * stray line cannot wipe recordings: `memo-discard-all` without
                 * a number does nothing but say what it would have needed. */
                if(!setup && strncmp(command,"memo-discard-all",16)==0) {
                    const char *argument=command+16;
                    while(*argument==' ') argument++;
                    char *end=NULL;
                    unsigned long expected=strtoul(argument,&end,10);
                    if(!*argument || (end && *end) || expected>1000)
                        printf("@ERROR expected_count_required\n");
                    else recorder_discard_all((unsigned)expected);
                }
                /* Screen diagnostics from docs/DEVELOPMENT_GUIDE.md. Read-only:
                 * they draw into the live framebuffer and never touch the
                 * recorder, journal or network state. */
                if(!setup && strcmp(command,"epd-clear")==0) screen_refresh();
                if(!setup && strncmp(command,"epd-window ",11)==0) {
                    unsigned bx,y,bw,h;
                    if(sscanf(command+11,"%u %u %u %u",&bx,&y,&bw,&h)==4)
                        screen_window_test(bx,y,bw,h);
                    else printf("@ERROR usage: epd-window <bx> <y> <bw> <h>\n");
                }
                if(!setup && strncmp(command,"text-test ",10)==0) {
                    unsigned which; int consumed=0;
                    if(sscanf(command+10,"%u%n",&which,&consumed)==1 && which<=2) {
                        const char *text=command+10+consumed;
                        while(*text==' ') text++;
                        screen_text_test(which,text);
                    } else printf("@ERROR usage: text-test <0|1|2> <text>\n");
                }
                if(!setup && strcmp(command,"icon-test")==0) screen_icon_test();
                if(!setup && strcmp(command,"pattern-test")==0) screen_pattern_test(STRIP_SOLID+1);
                if(!setup && strncmp(command,"pattern-test ",13)==0) {
                    unsigned step;
                    if(sscanf(command+13,"%u",&step)==1 && step<=STRIP_SOLID) screen_pattern_test(step);
                    else printf("@ERROR usage: pattern-test <0..4>\n");
                }
                if(!setup && strcmp(command,"status-test")==0) screen_status_test(0);
                if(!setup && strncmp(command,"status-test ",12)==0) {
                    unsigned demo;
                    if(sscanf(command+12,"%u",&demo)==1 && demo>=1 && demo<=5) screen_status_test(demo);
                    else printf("@ERROR usage: status-test <1..5>\n");
                }
                if(!setup && strcmp(command,"header-test")==0) screen_header_test(0);
                if(!setup && strncmp(command,"header-test ",12)==0) {
                    unsigned demo;
                    if(sscanf(command+12,"%u",&demo)==1 && demo>=1 && demo<=6) screen_header_test(demo);
                    else printf("@ERROR usage: header-test <1..6>\n");
                }
                if(!setup && strcmp(command,"card-test")==0) screen_card_test();
                command_len=0;
            } else if(command_len<sizeof(command)-1) command[command_len++]=ch;
        }
        held = gpio_get_level(GPIO_NUM_0) == 0 ? held + 1 : 0;
        bool middle_down=gpio_get_level(GPIO_NUM_5)==0;
        /* The temporary portal owns the middle key: a short press is the
         * always-visible, device-local escape path and can never start audio. */
        if (portal_active && atomic_load(&portal_cancellable)) {
            if (middle_down) middle_ticks++;
            else {
                if (middle_ticks > 0)
                    atomic_store(&portal_cancel_requested, true);
                middle_ticks = 0;
            }
            recording_gesture = false;
            if (!setup) recorder_hold(false);
        // A short middle press is reserved for dashboard selection. Audio starts
        // only after 450 ms, so opening a card cannot create a mini recording.
        } else if(!setup) {
            if(middle_down) {
                middle_ticks++;
                if(middle_ticks>=5) recording_gesture=true;
            } else {
                if(middle_ticks>0 && !recording_gesture) {
                    printf("@UI select dashboard\n");
                    screen_focus_activate();
                }
                middle_ticks=0;
                recording_gesture=false;
            }
            recorder_hold(recording_gesture && middle_down);

            /* Up and down move the focus. Deliberately edge triggered: a
             * refresh takes about half a second, so repeating while a key is
             * held would only pile up work the panel cannot show. While the
             * middle key is held the panel belongs to the recorder, so the
             * focus keys stay inert — their level is still tracked, or the
             * release after a recording would read as a fresh press. */
            bool up_down = gpio_get_level(GPIO_NUM_4) == 0;
            bool down_down = gpio_get_level(GPIO_NUM_6) == 0;
            if (!recording_gesture && !recorder_busy()) {
                if (up_down && !up_was_down) screen_focus_move(-1);
                if (down_down && !down_was_down) screen_focus_move(1);
            }
            up_was_down = up_down;
            down_was_down = down_down;
        }
        if (!setup && !portal_active && held == 30 && !recorder_busy()) {
            if (nvs_open("notebook", NVS_READWRITE, &n) == ESP_OK) {
                esp_err_t err = nvs_set_u8(n, "setup", 1);
                if (err == ESP_OK) err = nvs_commit(n);
                nvs_close(n);
                if (err == ESP_OK) esp_restart();
            }
        }
        /* Ten second link check. It also corrects the status bar downwards: a
         * lost WIFI_EVENT_STA_DISCONNECTED would otherwise leave the connected
         * symbol standing forever, because nothing else ever revises it. Only
         * downwards — the association alone does not mean the device can reach
         * anything, so raising the symbol stays with IP_EVENT_STA_GOT_IP. */
        if (!setup && !portal_active && ++ticks >= 100) {
            ticks = 0;
            wifi_ap_record_t ap;
            if (esp_wifi_sta_get_ap_info(&ap) != ESP_OK) {
                screen_status_network(false);
                unsigned next = network_configuration.network_count > 1
                    ? (active_network + 1) % network_configuration.network_count
                    : active_network;
                esp_err_t err = select_network(next, true);
                if (err != ESP_OK)
                    printf("@WIFI retry_failed=%s profile=%u/%u\n",
                           esp_err_to_name(err), next + 1,
                           network_configuration.network_count);
            }
        }
    }
}
