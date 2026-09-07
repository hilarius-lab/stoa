#include <stdio.h>
#include <stdbool.h>
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
#include <fcntl.h>
#include <unistd.h>
#include "driver/usb_serial_jtag.h"
#include "driver/usb_serial_jtag_vfs.h"

static const char page[] =
"<!doctype html><html lang=de><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
"<title>Notebook einrichten</title><style>body{font:18px system-ui;max-width:420px;margin:40px auto;padding:20px;background:#f5f3ee}"
"input,button{box-sizing:border-box;width:100%;padding:12px;margin:8px 0 20px}button{background:#183e34;color:white;border:0}label{display:block}</style>"
"<h1>Notebook einrichten</h1><p>Verbinde dein Notebook mit einem 2,4-GHz-WLAN.</p>"
"<form><label>WLAN-Name<input id=s maxlength=32 required></label><label>WLAN-Passwort<input id=p type=password maxlength=63 autocomplete=new-password></label>"
"<label>Serveradresse (optional)<input id=u type=url placeholder='http://192.168.1.100:8000' maxlength=255></label>"
"<label>Enrollment-Code (optional)<input id=e maxlength=200 autocomplete=off></label>"
"<p>Zum WLAN-Test leer lassen. Ein Backend ist nicht erforderlich. HTTP ist fuer lokale Tests erlaubt.</p><button>Speichern</button></form><p id=r role=status></p>"
"<script>document.querySelector('form').onsubmit=async e=>{e.preventDefault();let b=document.querySelector('button');b.disabled=true;"
"try{let a=await fetch('/configure',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ssid:document.querySelector('#s').value,password:document.querySelector('#p').value,server:document.querySelector('#u').value,enrollment_code:document.querySelector('#e').value})});"
"document.querySelector('#r').textContent=await a.text()}catch(e){document.querySelector('#r').textContent='Verbindung unterbrochen. Bitte erneut versuchen.'}b.disabled=false}</script></html>";

static esp_err_t root(httpd_req_t *r) {
    httpd_resp_set_type(r, "text/html; charset=utf-8");
    httpd_resp_set_hdr(r, "Cache-Control", "no-store");
    return httpd_resp_send(r, page, HTTPD_RESP_USE_STRLEN);
}

static esp_err_t configure(httpd_req_t *r) {
    char body[1024];
    if (r->content_len == 0 || r->content_len >= sizeof(body))
        return httpd_resp_send_err(r, HTTPD_400_BAD_REQUEST, "Ungueltige Eingabe.");
    size_t used = 0;
    while (used < r->content_len) {
        int count = httpd_req_recv(r, body + used, r->content_len - used);
        if (count <= 0) return ESP_FAIL;
        used += count;
    }
    body[used] = 0;
    cJSON *j = cJSON_Parse(body);
    cJSON *s = cJSON_GetObjectItemCaseSensitive(j, "ssid");
    cJSON *p = cJSON_GetObjectItemCaseSensitive(j, "password");
    cJSON *u = cJSON_GetObjectItemCaseSensitive(j, "server");
    cJSON *e = cJSON_GetObjectItemCaseSensitive(j, "enrollment_code");
    const char *server_url = cJSON_IsString(u) ? u->valuestring : "";
    bool server_valid = !u || (cJSON_IsString(u) && (server_url[0] == '\0' ||
        (strncmp(server_url, "https://", 8) == 0 && strlen(server_url) > 8) ||
        (strncmp(server_url, "http://", 7) == 0 && strlen(server_url) > 7)));
    bool valid = cJSON_IsString(s) && cJSON_IsString(p) && server_valid && (!e || cJSON_IsString(e));
    if (valid) valid = strlen(s->valuestring) > 0 && strlen(s->valuestring) <= 32 &&
        (strlen(p->valuestring) == 0 || strlen(p->valuestring) >= 8) && strlen(p->valuestring) <= 63 &&
        strlen(server_url) <= 255 && (!cJSON_IsString(e) || strlen(e->valuestring) <= 200);
    if (!valid) {
        cJSON_Delete(j);
        return httpd_resp_send_err(r, HTTPD_400_BAD_REQUEST, "WLAN ungueltig. Serveradresse leer lassen oder HTTP/HTTPS verwenden.");
    }
    // One blob prevents partial multi-key configuration updates.
    nvs_handle_t n;
    esp_err_t err = nvs_open("notebook", NVS_READWRITE, &n);
    if (err == ESP_OK) {
        if (cJSON_IsString(e) && e->valuestring[0]) err=nvs_set_str(n,"enroll",e->valuestring);
        cJSON_DeleteItemFromObjectCaseSensitive(j, "enrollment_code");
        char *encoded=cJSON_PrintUnformatted(j);
        if (err == ESP_OK) err = encoded ? nvs_set_str(n, "config", encoded) : ESP_ERR_NO_MEM;
        if (err == ESP_OK) err = nvs_set_u8(n, "setup", 0);
        if (err == ESP_OK) err = nvs_commit(n);
        if(encoded){memset(encoded,0,strlen(encoded));cJSON_free(encoded);}
        nvs_close(n);
    }
    cJSON_Delete(j);
    memset(body, 0, sizeof(body));
    if (err != ESP_OK) return httpd_resp_send_err(r, HTTPD_500_INTERNAL_SERVER_ERROR, "Speichern fehlgeschlagen.");
    screen_show(SCREEN_SAVED, NULL);
    httpd_resp_set_type(r, "text/plain; charset=utf-8");
    return httpd_resp_sendstr(r, "Gespeichert. Bitte das Geraet neu starten. Die WLAN-Verbindung wird dann versucht.");
}

static void wifi_event(void *arg, esp_event_base_t base, int32_t id, void *data) {
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) esp_wifi_connect();
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        printf("WLAN getrennt; erneuter Versuch.\n");
        screen_status_network(false);
        // Retry scheduling occurs in app_main, without blocking the event loop.
    }
    if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
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
    char stored[1024] = {0}; size_t len = sizeof(stored); nvs_handle_t n;
    uint8_t force_setup = 0;
    if (nvs_open("notebook", NVS_READONLY, &n) == ESP_OK) {
        if (nvs_get_str(n, "config", stored, &len) != ESP_OK) stored[0] = 0;
        nvs_get_u8(n, "setup", &force_setup);
        nvs_close(n);
    }
    cJSON *j = cJSON_Parse(stored);
    cJSON *s = cJSON_GetObjectItemCaseSensitive(j, "ssid");
    cJSON *p = cJSON_GetObjectItemCaseSensitive(j, "password");
    cJSON *u = cJSON_GetObjectItemCaseSensitive(j, "server");
    bool setup = !cJSON_IsString(s) || !cJSON_IsString(p) || force_setup;
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    /* After esp_netif_init and not before: SNTP registers itself with the lwIP
     * task, and calling it earlier aborts on an invalid mailbox — a boot loop,
     * not a warning. Starting it here also covers the setup-portal case, where
     * it simply never synchronises because there is no upstream network. */
    clock_start();
    if (setup) esp_netif_create_default_wifi_ap(); else esp_netif_create_default_wifi_sta();
    wifi_init_config_t init = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&init));
    ESP_ERROR_CHECK(esp_wifi_set_storage(WIFI_STORAGE_RAM));
    wifi_config_t cfg = {0};
    if (setup) {
        strcpy((char *)cfg.ap.ssid, "Notebook-Setup");
        snprintf((char *)cfg.ap.password, sizeof(cfg.ap.password), "%08lx%08lx", (unsigned long)esp_random(), (unsigned long)esp_random());
        cfg.ap.authmode = WIFI_AUTH_WPA2_PSK; cfg.ap.max_connection = 1; cfg.ap.channel = 1;
        ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_AP));
        ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_AP, &cfg));
        ESP_ERROR_CHECK(esp_wifi_start());
        // Intentional local onboarding output; never print home Wi-Fi credentials.
        printf("Einrichtung: Notebook-Setup / %s / http://192.168.4.1\n", cfg.ap.password);
        screen_show(SCREEN_SETUP, (char *)cfg.ap.password);
        httpd_config_t h = HTTPD_DEFAULT_CONFIG(); httpd_handle_t server;
        ESP_ERROR_CHECK(httpd_start(&server, &h));
        httpd_uri_t get = {.uri="/", .method=HTTP_GET, .handler=root};
        httpd_uri_t post = {.uri="/configure", .method=HTTP_POST, .handler=configure};
        ESP_ERROR_CHECK(httpd_register_uri_handler(server, &get));
        ESP_ERROR_CHECK(httpd_register_uri_handler(server, &post));
    } else {
        screen_show(SCREEN_CONNECTING, NULL);
        api_client_start(cJSON_IsString(u) ? u->valuestring : "");
        memcpy(cfg.sta.ssid, s->valuestring, strnlen(s->valuestring, sizeof(cfg.sta.ssid)));
        memcpy(cfg.sta.password, p->valuestring, strnlen(p->valuestring, sizeof(cfg.sta.password)));
        ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, wifi_event, NULL));
        ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, wifi_event, NULL));
        ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
        ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &cfg));
        ESP_ERROR_CHECK(esp_wifi_start());
    }
    cJSON_Delete(j); memset(stored, 0, sizeof(stored)); memset(&cfg, 0, sizeof(cfg));
    if(!setup) recorder_start();
    static char command[300]; size_t command_len=0;
    unsigned held = 0, ticks = 0, middle_ticks = 0;
    bool recording_gesture = false;
    /* Edge state of the two focus keys. They are read here and nowhere else, so
     * the previous level lives with the loop that samples it. */
    bool up_was_down = false, down_was_down = false;
    while (true) {
        vTaskDelay(pdMS_TO_TICKS(100));
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
        // A short middle press is reserved for dashboard selection. Audio starts
        // only after 450 ms, so opening a card cannot create a mini recording.
        if(!setup) {
            bool middle_down=gpio_get_level(GPIO_NUM_5)==0;
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
        if (!setup && held == 30 && !recorder_busy()) {
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
        if (!setup && ++ticks >= 100) {
            ticks = 0;
            wifi_ap_record_t ap;
            if (esp_wifi_sta_get_ap_info(&ap) != ESP_OK) {
                screen_status_network(false);
                esp_wifi_connect();
            }
        }
    }
}
