"""Persian (fa) translations, keyed by the exact English source string
passed to i18n.tr() in ui/*.py. See xrayui/i18n.py for the lookup rules.
"""
from __future__ import annotations

TRANSLATIONS_FA: dict[str, str] = {
    # -- titlebar.py ----------------------------------------------------
    "Close": "بستن",
    "Minimize": "کوچک کردن",
    "Zoom": "بزرگ‌نمایی",

    # -- tools_panel.py ---------------------------------------------------
    "Ping": "پینگ",
    "Relay TCP delay": "تأخیر TCP رله",
    "Throughput": "توان عبوری",
    "Baseline": "خط پایه",
    "Diagnostics": "عیب‌یابی",

    # -- subscription_panel.py -------------------------------------------
    "never": "هرگز",
    "{n}m ago": "{n} دقیقه پیش",
    "{n}h ago": "{n} ساعت پیش",
    "{n}d ago": "{n} روز پیش",
    "disabled": "غیرفعال",
    "{amount} left": "{amount} باقی‌مانده",
    "usage unknown": "مصرف نامشخص",
    "expires in {n}d": "انقضا تا {n} روز دیگر",
    "updated {ago}": "به‌روزرسانی {ago}",
    "Subscriptions": "اشتراک‌ها",
    "Update all": "به‌روزرسانی همه",
    "Add": "افزودن",
    "No subscriptions yet.": "هنوز اشتراکی وجود ندارد.",

    # -- rule_editor.py ---------------------------------------------------
    "Edit rule": "ویرایش قانون",
    "Remarks": "توضیحات",
    "Proxy": "پروکسی",
    "Direct": "مستقیم",
    "Block": "مسدود",
    "Action": "عملکرد",
    "Domains (one per line):": "دامنه‌ها (هر خط یک مورد):",
    "IPs / CIDRs (one per line):": "IPها / CIDR (هر خط یک مورد):",
    "Port": "پورت",
    "Any": "همه",
    "Network": "شبکه",
    "Protocol": "پروتکل",
    "Process": "فرایند",
    "Advanced": "پیشرفته",
    "Empty rule": "قانون خالی",
    "This rule would match nothing. Add at least one condition.":
        "این قانون با هیچ‌چیز مطابقت نخواهد داشت. حداقل یک شرط اضافه کنید.",

    # -- server_table.py --------------------------------------------------
    "Name": "نام",
    "Delay": "تأخیر",
    "Transport": "نوع انتقال",
    "Subscription": "اشتراک",
    "Type": "نوع",
    "n/a": "نامشخص",
    "Failed": "ناموفق",
    "QR — {name}": "کد QR — {name}",
    "Copy link": "کپی لینک",

    # -- ping mode and exit flags -------------------------------------------
    "Delay test": "آزمون تأخیر",
    "Round trip (like v2rayN)": "رفت‌وبرگشت (مثل v2rayN)",
    "First connection": "اتصال اول",
    "Round trip times a second request on the connection the first one "
    "opened, which is what v2rayN shows. First connection includes the "
    "time to set the connection up, so the numbers are higher.":
        "«رفت‌وبرگشت» درخواست دوم را روی همان اتصالی که درخواست اول باز کرده "
        "اندازه می‌گیرد؛ عددی که v2rayN نشان می‌دهد. «اتصال اول» زمان برقراری "
        "اتصال را هم شامل می‌شود و به همین دلیل عددها بزرگ‌تر است.",
    "First connection: {time}": "اتصال اول: {time}",
    "Exits in {country} · {ip}": "خروج از {country} · {ip}",
    "Exits in {country}": "خروج از {country}",
    "Press Test to find out where this server exits":
        "برای فهمیدن محل خروج این سرور، دکمهٔ تست را بزنید",

    # -- dns_dialog.py ------------------------------------------------------
    "Preset:": "الگو:",
    "Resolvers (one per line, in order):": "سرورهای DNS (هر خط یک مورد، به ترتیب):",
    "Leave empty to keep the template's servers.": "برای حفظ سرورهای پیش‌فرض قالب، خالی بگذارید.",
    "Use literal IPs — a hostname needs another resolver to look it up first.":
        "از آی‌پی مستقیم استفاده کنید — نام میزبان به یک سرور DNS دیگر برای یافتنش نیاز دارد.",
    "Query strategy:": "راهبرد پرس‌وجو:",
    "Template default": "پیش‌فرض قالب",
    "Static overrides (domain = address):": "بازنویسی‌های ثابت (دامنه = آدرس):",
    "Domestic DNS (for sites that go direct):": "DNS داخلی (برای سایت‌هایی که مستقیم می‌روند):",
    "Off": "خاموش",
    "Resolve other sites through the tunnel": "پرس‌وجوی DNS سایر سایت‌ها از طریق تونل",
    "DNS queries for other sites go through the tunnel; "
    "the proxy and any resolver hostname still resolve directly.":
        "پرس‌وجوهای DNS برای سایر سایت‌ها از طریق تونل انجام می‌شود؛ "
        "پروکسی و هر نام میزبان سرور DNS همچنان مستقیم پرس‌وجو می‌شوند.",
    "DNS queries leave over your normal connection, not the tunnel.":
        "پرس‌وجوهای DNS از اتصال عادی شما خارج می‌شوند، نه از تونل.",
    "Parallel query": "پرس‌وجوی موازی",
    "Serve stale": "پاسخ‌گویی با داده کهنه",
    "Raw DNS override (replaces everything above):": "بازنویسی خام DNS (جایگزین همه موارد بالا):",
                "Validating…": "در حال بررسی…",
    "Validation failed": "بررسی ناموفق بود",

    # -- core/dns.py validation-reason templates (value + template, see
    # ui/dns_dialog.py._save) -- {value} is the user's own raw input and
    # stays untranslated wherever it appears.
    "{value}: a server address cannot contain spaces": "{value}: آدرس سرور نمی‌تواند فاصله داشته باشد",
    "{value}: no server after the scheme": "{value}: پس از پیشوند، سروری مشخص نشده است",
    "{value}: a port needs a scheme — try udp://{value} or tcp://{value}":
        "{value}: پورت به یک پیشوند نیاز دارد — udp://{value} یا tcp://{value} را امتحان کنید",
    "{value}: expected an IP, a hostname, or a scheme such as https:// tcp:// udp:// quic://":
        "{value}: یک آی‌پی، نام میزبان یا پیشوندی مانند https:// tcp:// udp:// quic:// موردنیاز است",
    "{value}: invalid port": "{value}: پورت نامعتبر",
    "{value}: use the resolver's IP address": "{value}: از آدرس آی‌پی سرور DNS استفاده کنید",
    "{value}: asks the OS resolver, which this app points back at Xray — a loop":
        "{value}: از سرور DNS سیستم‌عامل می‌پرسد که این برنامه آن را دوباره به Xray برمی‌گرداند — یک حلقه",
    "{value}: needs a matching inbound and sniffing setup this app does not ship":
        "{value}: به یک ورودی و تنظیم sniffing متناظر نیاز دارد که این برنامه ارائه نمی‌دهد",

    # -- widgets.py ---------------------------------------------------------
    "Connection": "اتصال",
    "DISCONNECTED": "قطع شده",
    "CONNECTED": "متصل",
    "Relay": "رله",
    "Xray process": "پردازه Xray",
    "Interface": "رابط شبکه",
    "Source IPv4": "IPv4 مبدأ",
    "Gateway": "دروازه",
    "Tunnel ifIndex": "ifIndex تونل",
    "Used this session": "مصرف این نشست",
    "Servers": "سرورها",
    "Filter by name or address…": "فیلتر بر اساس نام یا آدرس…",
    "Import": "وارد کردن",
    "Test": "تست",
    "Real delay": "تأخیر واقعی",
    "TCP ping": "پینگ TCP",
    "Use fastest": "استفاده از سریع‌ترین",
    "Remove failed": "حذف ناموفق‌ها",
    "Remove duplicates": "حذف موارد تکراری",
    "Cancel": "انصراف",
    "No share link": "بدون لینک اشتراک",
    "No share link for this server type.": "برای این نوع سرور لینک اشتراکی وجود ندارد.",
    "Set active": "تنظیم به‌عنوان فعال",
    "Edit": "ویرایش",
    "Clone": "تکثیر",
    "Test real delay": "تست تأخیر واقعی",
    "Copy share link": "کپی لینک اشتراک",
    "Show QR": "نمایش QR",
    "Delete": "حذف",

    # -- routing_dialog.py ----------------------------------------------
    "Match": "مورد تطبیق",
    "port {port}/{network}": "پورت {port}/{network}",
    "port {port}": "پورت {port}",
    "{n} process(es)": "{n} فرایند",
    "(matches everything)": "(با همه‌چیز مطابقت دارد)",
    "(no remarks)": "(بدون توضیحات)",
    "Bypass & routing": "دور زدن و مسیریابی",
    "Active routing:": "مسیریابی فعال:",
    "Simple": "ساده",
    "Rule sets": "مجموعه قوانین",
    "Bypass the tunnel (go direct)": "دور زدن تونل (مستقیم)",
    "Low usage — bypass Windows telemetry/update chatter":
        "مصرف کم — دور زدن ترافیک تله‌متری/به‌روزرسانی ویندوز",
    "Low usage — bypass macOS update/telemetry chatter":
        "مصرف کم — دور زدن ترافیک به‌روزرسانی/تله‌متری macOS",
    "Block ads && trackers": "مسدودسازی تبلیغات و ردیاب‌ها",
    "Local network / private IPs direct": "شبکه محلی / آی‌پی‌های خصوصی مستقیم",
    "Iran sites && IPs direct": "سایت‌ها و آی‌پی‌های ایران مستقیم",
    "Russia sites && IPs direct": "سایت‌ها و آی‌پی‌های روسیه مستقیم",
    "China sites && IPs direct": "سایت‌ها و آی‌پی‌های چین مستقیم",
    "Bypass domains (one per line — direct):": "دامنه‌های مستقیم (هر خط یک مورد):",
    "Bypass IPs / CIDRs (one per line — direct):": "IPها / CIDR مستقیم (هر خط یک مورد):",
    "Force through tunnel (one per line — proxy):": "اجبار به تونل (هر خط یک مورد):",
    "Empty": "خالی",
    "Global": "سراسری",
    "Like Simple": "مشابه ساده",
    "Chocolate4U Iran rules": "قوانین ایران Chocolate4U",
    "Duplicate": "تکثیر",
    "From file…": "از فایل…",
    "From clipboard": "از کلیپ‌بورد",
    "From URL…": "از URL…",
    "Export": "خروجی گرفتن",
    "To file…": "به فایل…",
    "Copy to clipboard": "کپی به کلیپ‌بورد",
    "Name:": "نام:",
    "Domain strategy:": "راهبرد دامنه:",
    "Inherit": "به ارث بردن",
    "Unnamed": "بدون‌نام",
    "Fetching Chocolate4U Iran rules…": "در حال دریافت قوانین ایران Chocolate4U…",
    "Import failed": "وارد کردن ناموفق بود",
    "Nothing to import.": "چیزی برای وارد کردن نیست.",
    "Imported {n} set(s), skipped {skipped} rule(s).":
        "{n} مجموعه وارد شد، {skipped} قانون نادیده گرفته شد.",
    "Delete set": "حذف مجموعه",
    "Delete '{name}'?": "'{name}' حذف شود؟",
    "Import rule sets": "وارد کردن مجموعه قوانین",
    "Import from URL": "وارد کردن از URL",
    "URL:": "URL:",
    "Fetching {url}…": "در حال دریافت {url}…",
    "Copied to clipboard.": "در کلیپ‌بورد کپی شد.",
    "Export rule set": "خروجی گرفتن از مجموعه قوانین",
    "Export failed": "خروجی گرفتن ناموفق بود",

    # -- dialogs.py: ImportDialog ------------------------------------------
    "Import profiles": "وارد کردن سرورها",
    "Paste vless:// or wireguard:// links, a WireGuard .conf, or a base64 subscription…":
        "لینک‌های vless:// یا wireguard://، یک فایل WireGuard .conf یا یک اشتراک base64 را جای‌گذاری کنید…",
    "Paste a full Xray config, a WireGuard .conf, or a profile JSON…":
        "یک پیکربندی کامل Xray، فایل WireGuard .conf یا JSON یک سرور را جای‌گذاری کنید…",
    "Link / Subscription": "لینک / اشتراک",
    "QR image": "تصویر QR",
    "Choose image…": "انتخاب تصویر…",
    "Decode a vless:// or wireguard:// link from a QR code image.":
        "یک لینک vless:// یا wireguard:// را از تصویر کد QR بخوان.",
    "No valid profiles found.": "هیچ سرور معتبری یافت نشد.",

    # -- dialogs.py: ProfileEditDialog --------------------------------------
    "Edit profile": "ویرایش سرور",
    "Form": "فرم",
    "Raw JSON": "JSON خام",
    "Address": "آدرس",
    "UUID / private key": "UUID / کلید خصوصی",
    "Peer / Reality public key": "کلید عمومی Peer / Reality",
    "VMess security": "امنیت VMess",
    "Method": "روش",
    "Encryption": "رمزگذاری",
    "Flow": "جریان (Flow)",
    "Security": "امنیت",
    "Fingerprint": "اثر انگشت TLS",
    "Reality sid": "شناسه کوتاه (sid) در Reality",
    "Reality spiderX": "spiderX در Reality",
    "Path": "مسیر",
    "Host": "میزبان",
    "gRPC service": "سرویس gRPC",
    "Pinned cert SHA-256": "SHA-256 گواهی پین‌شده",
    "Obfuscation password": "رمز عبور مبهم‌سازی",
    "Local address": "آدرس محلی",
    "Preshared key": "کلید از‌پیش‌مشترک",
    "Reserved": "رزرو شده",
    "Keepalive (s)": "Keepalive (ثانیه)",
    "Header type": "نوع هدر",
    "xhttp extra (JSON)": "xhttp extra (JSON)",
    "ECH config list": "فهرست تنظیمات ECH",
    "Verify cert name": "تأیید نام گواهی",
    "Port-hopping range": "بازه پورت‌پرشی",
    "Hop interval (s)": "فاصله پرش (ثانیه)",
    "This server's link asks to skip certificate checks. This Xray "
    "version no longer allows that — pin the certificate's SHA-256 "
    "instead.":
        "لینک این سرور درخواست نادیده گرفتن بررسی گواهی را دارد. این نسخه از Xray دیگر "
        "این کار را مجاز نمی‌داند — به‌جای آن SHA-256 گواهی را پین کنید.",
    "Private key": "کلید خصوصی",
    "Password": "رمز عبور",
    "Peer public key": "کلید عمومی Peer",
    "Reality public key": "کلید عمومی Reality",
    "Invalid JSON": "JSON نامعتبر",
    "A server is written as one JSON object, inside { }.":
        "هر سرور به‌صورت یک شیء JSON داخل { } نوشته می‌شود.",
    "Invalid xhttp extra": "xhttp extra نامعتبر",
    "xhttp extra must be a JSON object, e.g. {\"headers\": {\"X-Extra\": \"1\"}}.":
        "xhttp extra باید یک شیء JSON باشد، مثلاً {\"headers\": {\"X-Extra\": \"1\"}}.",
    "Invalid port range": "بازه پورت نامعتبر",
    "Port-hopping range must look like 20000-30000 "
    "(or a comma-separated list of ranges/ports), "
    "with every port 1-65535.":
        "بازه پورت‌پرشی باید مانند 20000-30000 باشد (یا فهرستی از بازه‌ها/پورت‌ها با کاما جدا شده)، "
        "با هر پورت بین 1 تا 65535.",
    "Invalid pinned certificate": "گواهی پین‌شده نامعتبر",
    "Pinned cert SHA-256 must be 64 hex characters "
    "(colons and spaces are fine and will be removed).":
        "SHA-256 گواهی پین‌شده باید 64 کاراکتر هگز باشد "
        "(دونقطه و فاصله مشکلی ندارد و حذف خواهد شد).",
    "Missing fields": "فیلدهای ناقص",
    "Address and UUID / private key are required.": "آدرس و UUID / کلید خصوصی الزامی هستند.",
    "WireGuard peer public key is required.": "کلید عمومی Peer در WireGuard الزامی است.",
    "Default": "پیش‌فرض",
    "0 lets Xray pick its own default. Otherwise 5-3600 seconds.":
        "0 یعنی Xray مقدار پیش‌فرض خودش را انتخاب کند. در غیر این صورت 5 تا 3600 ثانیه.",
    "Leave 0 to let the congestion control pick (BBR).":
        "برای انتخاب خودکار توسط کنترل ازدحام (BBR) روی 0 بگذارید.",

    # -- dialogs.py: SettingsDialog ------------------------------------------
    "Settings": "تنظیمات",
    "Ping target": "مقصد پینگ",
    "Throughput sample (s)": "نمونه‌برداری توان عبوری (ثانیه)",
    "Tunnel MTU": "MTU تونل",
    "Tunnel MTU. Lower leaves more headroom for encapsulation; "
    "higher reduces per-packet overhead. 1420 is a safe default.":
        "MTU تونل. مقدار کمتر فضای بیشتری برای کپسوله‌سازی می‌گذارد؛ "
        "مقدار بیشتر سربار هر بسته را کاهش می‌دهد. 1420 مقداری امن و پیش‌فرض است.",
    "Xray log level": "سطح لاگ Xray",
    "Check for updates": "بررسی به‌روزرسانی",
    "Geo data": "داده‌های جغرافیایی",
    "Source": "منبع",
    "Update now": "به‌روزرسانی اکنون",
    "Auto-update every (hours)": "به‌روزرسانی خودکار هر (ساعت)",
    "Startup": "راه‌اندازی",
    "Start sushTun when I log in": "اجرای sushTun هنگام ورود من",
    "Start minimized to the tray": "شروع به‌صورت کوچک‌شده در نوار سیستم",
    "Connect automatically on start": "اتصال خودکار هنگام شروع",
    "Backup && restore": "پشتیبان‌گیری و بازیابی",
    "A backup file contains your server passwords in plain text — "
    "store and share it carefully.":
        "فایل پشتیبان شامل رمزهای عبور سرورهای شماست به‌صورت متن ساده — "
        "آن را با احتیاط نگه‌داری و به اشتراک بگذارید.",
    "Back up…": "پشتیبان‌گیری…",
    "Restore…": "بازیابی…",
    "Anti-filter": "ضدفیلتر",
    "Enabled": "فعال",
    "Packets": "بسته‌ها",
    "Length": "طول",
    "Interval": "فاصله زمانی",
    "Max split": "حداکثر تقسیم",
    "Multiplexing": "چندگانه‌سازی (Multiplexing)",
    "Concurrency": "هم‌روندی",
    "Sniffing": "شناسایی ترافیک (Sniffing)",
    "Route only": "فقط مسیریابی",
    "Local proxy": "پروکسی محلی",
    "User": "کاربر",
    "LAN sharing is on with no password — anyone on your network can use this proxy.":
        "اشتراک‌گذاری در شبکه محلی بدون رمز عبور فعال است — هرکسی در شبکه شما می‌تواند "
        "از این پروکسی استفاده کند.",
    "Default TLS fingerprint": "اثر انگشت پیش‌فرض TLS",
    "(off)": "(خاموش)",
    "Never updated": "هرگز به‌روزرسانی نشده",
    "Updated {n}m ago": "{n} دقیقه پیش به‌روزرسانی شد",
    "Updated {n}h ago": "{n} ساعت پیش به‌روزرسانی شد",
    "Updating…": "در حال به‌روزرسانی…",
    "Back up sushTun": "پشتیبان‌گیری از sushTun",
    "Backup failed": "پشتیبان‌گیری ناموفق بود",
    "Backup complete": "پشتیبان‌گیری کامل شد",
    "Saved to {path}": "در {path} ذخیره شد",
    "Restore sushTun backup": "بازیابی پشتیبان sushTun",
    "Restore backup": "بازیابی پشتیبان",
    "This replaces your current servers and settings with the backup's. Continue?":
        "این کار سرورها و تنظیمات فعلی شما را با نسخه پشتیبان جایگزین می‌کند. ادامه می‌دهید؟",
    "Restore failed": "بازیابی ناموفق بود",
    "Restore complete": "بازیابی کامل شد",
    "Restored. sushTun will reload your settings and servers.":
        "بازیابی شد. sushTun تنظیمات و سرورهای شما را دوباره بارگذاری می‌کند.",
    "Settings invalid": "تنظیمات نامعتبر است",
    "Startup setting failed": "تنظیم راه‌اندازی ناموفق بود",
    "Not supported on macOS yet.": "هنوز در macOS پشتیبانی نمی‌شود.",
    "Install the .deb package to start sushTun at login.":
        "برای اجرای sushTun هنگام ورود، بسته .deb را نصب کنید.",
    "Can't tell which user to start sushTun for.":
        "مشخص نیست sushTun باید برای کدام کاربر اجرا شود.",

    # -- dialogs.py: SubscriptionEditDialog ----------------------------------
    "Edit subscription": "ویرایش اشتراک",
    "0 (default)": "0 (پیش‌فرض)",
    "Only keep servers whose name matches (regex)": "فقط سرورهایی که نامشان مطابقت دارد (regex)",
    "Name filter": "فیلتر نام",
    "Missing URL": "URL موجود نیست",
    "Subscription URL is required.": "URL اشتراک الزامی است.",
    "Invalid name filter": "فیلتر نام نامعتبر است",

    # -- core/alerts.py (value+template, see ui/main_window.py._check_alerts) -
    "Critical: only {amount} data left": "هشدار جدی: فقط {amount} داده باقی مانده",
    "Low data: {amount} left ({percent})": "داده کم: {amount} باقی مانده ({percent})",
    "Subscription expires in {n} days": "اشتراک تا {n} روز دیگر منقضی می‌شود",

    # -- hover help (help.py): what each control does, plus an example ---
    "How long this connection has been up.":
        "مدت زمانی که این اتصال برقرار بوده.",
    "Handy for noticing that a call dropped the tunnel an hour ago.":
        "اگر وسط یک تماس تونل قطع شده باشد، از روی این زمان می‌فهمید.",
    "Turns the tunnel on. Your internet then goes through the active server (the one with the dot), following your routing rules.":
        "تونل را روشن می‌کند. از این به بعد اینترنت شما با قوانین مسیریابی از طریق سرور فعال (همان که کنارش نقطه دارد) می‌رود.",
    "Press it before settling into a café's Wi-Fi, then forget about it.":
        "قبل از نشستن پشت وای‌فای کافه بزنیدش و دیگر فراموشش کنید.",
    "Turns the tunnel off and puts your network back the way it was.":
        "تونل را خاموش می‌کند و شبکه را به همان حالت قبلی برمی‌گرداند.",
    "A site that dislikes VPNs? One click and you're on your normal connection again.":
        "سایتی با VPN کنار نمی‌آید؟ یک کلیک و دوباره روی اینترنت معمولی خودتان هستید.",
    "The server you are using, its protocol and delay, the network adapter, and the country your traffic comes out in.":
        "سروری که استفاده می‌کنید، پروتکل و تأخیرش، کارت شبکه‌ای که کار می‌کند و کشوری که ترافیک شما از آنجا بیرون می‌آید.",
    "Flag not where you wanted to be? Pick another server.":
        "پرچم کشوری نیست که می‌خواستید؟ یک سرور دیگر انتخاب کنید.",
    "How fast data is flowing through the tunnel right now.":
        "همین حالا چقدر داده از تونل رد می‌شود.",
    "Watch it while a download runs to see what the server can really do.":
        "وسط یک دانلود نگاهش کنید تا ببینید سرور واقعاً چقدر زور دارد.",
    "How much data has gone through the tunnel since you connected.":
        "از لحظه‌ای که وصل شدید تا حالا چقدر داده از تونل گذشته است.",
    "Keeping an eye on a monthly data cap? Check it here.":
        "حجم ماهانه دارید و حواستان به آن است؟ همین‌جا ببینید.",
    "Restarts the connection so the change you just made takes effect.":
        "اتصال را از نو راه می‌اندازد تا تغییری که همین الان دادید اعمال شود.",
    "Changed the routing mode while connected? Press this and it applies in a few seconds.":
        "وقتی وصلید حالت مسیریابی را عوض کردید؟ این را بزنید تا چند ثانیه‌ی دیگر اعمال شود.",
    "Extra tools for when the connection misbehaves.":
        "ابزارهای اضافه برای وقتی اتصال بدقلقی می‌کند.",
    "The internet feels stuck after a crash? Open this and restore the network.":
        "بعد از یک خرابی اینترنت قفل کرده؟ این منو را باز کنید و شبکه را بازگردانی کنید.",
    "Undoes the tunnel's changes to your routes, DNS and hotspot sharing so the internet works normally again.":
        "تغییراتی را که تونل در مسیرها، DNS و اشتراک هات‌اسپات داده برمی‌گرداند تا اینترنت دوباره عادی کار کند.",
    "Closed the app badly and now no site loads? Try this first.":
        "برنامه را بد بستید و حالا هیچ سایتی باز نمی‌شود؟ اول این را امتحان کنید.",
    "The largest packet WireGuard sends (MTU). Lower it if big pages stall.":
        "بزرگ‌ترین بسته‌ای که WireGuard می‌فرستد (MTU). اگر صفحه‌های سنگین گیر می‌کنند آن را کمتر کنید.",
    "Paste share links (vless://, vmess://, trojan:// and so on), a WireGuard .conf, or a subscription address.":
        "لینک‌های اشتراکی (مثل vless://، vmess:// و trojan://)، یک فایل WireGuard .conf یا آدرس یک اشتراک را اینجا بچسبانید.",
    "A friend's message with a link? Paste the whole thing.":
        "دوستتان یک لینک فرستاده؟ کل متن را همین‌جا بچسبانید.",
    "Paste a full Xray config, a WireGuard .conf or a profile in JSON.":
        "یک پیکربندی کامل Xray، یک فایل WireGuard .conf یا یک پروفایل JSON را اینجا بچسبانید.",
    "Moving a server over from another app that exports JSON.":
        "وقتی می‌خواهید سروری را از برنامه‌ای که خروجی JSON می‌دهد منتقل کنید.",
    "Pick a picture (png, jpg or bmp) that contains a QR code.":
        "یک عکس (png، jpg یا bmp) که کد QR داخلش باشد انتخاب کنید.",
    "Screenshot the QR code, then choose the screenshot.":
        "از کد QR اسکرین‌شات بگیرید و همان را انتخاب کنید.",
    "The picture that will be read. Use the button to choose another.":
        "عکسی که خوانده می‌شود. برای عوض کردنش از دکمه استفاده کنید.",
    "Empty? Press Choose image.":
        "خالی است؟ «انتخاب تصویر» را بزنید.",
    "The whole server as JSON, one object inside { }.":
        "کل سرور به‌صورت JSON، یک شیء داخل { }.",
    "Handy for experts; most people can ignore it.":
        "برای حرفه‌ای‌ها؛ بیشتر آدم‌ها می‌توانند نادیده‌اش بگیرند.",
    "Shows the rarely needed fields.":
        "فیلدهایی را نشان می‌دهد که کمتر لازم می‌شوند.",
    "Skip it unless your provider's instructions mention one.":
        "اگر راهنمای ارائه‌دهنده‌تان اسمی از این‌ها نبرده، سراغشان نروید.",
    "How this subscription is named in your lists.":
        "اسمی که این اشتراک در فهرست‌هایتان دارد.",
    "Your provider's name, so you know whose servers these are.":
        "اسم ارائه‌دهنده، تا بدانید این سرورها مال کیست.",
    "The web address that hands out the server list.":
        "آدرس اینترنتی که فهرست سرورها را می‌دهد.",
    "Paste the link your provider gave you.":
        "لینکی را که ارائه‌دهنده به شما داده بچسبانید.",
    "A subscription that is switched off is kept but skipped by Update all.":
        "اشتراکِ خاموش نگه داشته می‌شود، ولی «به‌روزرسانی همه» از آن رد می‌شود.",
    "Pause a provider whose plan ran out without losing the link.":
        "اشتراکی که حجمش تمام شده را بدون گم کردن لینک موقتاً کنار بگذارید.",
    "How often this list refreshes by itself. 0 uses the app-wide interval.":
        "هر چند ساعت یک‌بار این فهرست خودش به‌روز شود. صفر یعنی همان فاصله‌ی کلی برنامه.",
    "24 refreshes it once a day.":
        "عدد 24 یعنی روزی یک‌بار.",
    "A pattern (regex) for server names. Only servers whose name matches it are kept; empty keeps them all.":
        "یک الگو (regex) برای اسم سرورها. فقط سرورهایی که اسمشان با آن بخواند می‌مانند؛ خالی یعنی همه می‌مانند.",
    "DE|NL keeps just the German and Dutch servers.":
        "DE|NL فقط سرورهای آلمان و هلند را نگه می‌دارد.",
    "The app name sent when downloading the list. Some providers send different lists depending on it.":
        "اسمی که موقع دانلود فهرست فرستاده می‌شود. بعضی ارائه‌دهنده‌ها بسته به آن فهرست متفاوتی می‌دهند.",
    "Leave the default unless your provider tells you to change it.":
        "اگر ارائه‌دهنده نگفته عوضش کنید، همان پیش‌فرض را نگه دارید.",
    "Reads a link from a picture of a QR code.":
        "لینک را از روی عکسِ یک کد QR می‌خواند.",
    "A screenshot of the QR code your provider showed you.":
        "اسکرین‌شاتی از کد QR که ارائه‌دهنده نشانتان داده.",
    "The usual fields, one per setting.":
        "فیلدهای معمول، هر تنظیم یک فیلد.",
    "Fix a port or a name without touching anything else.":
        "پورت یا اسم را درست کنید بی‌آنکه به چیز دیگری دست بزنید.",
    "The whole server as JSON. When this tab is open, Save uses the JSON instead of the form.":
        "کل سرور به‌صورت JSON. وقتی این برگه باز است، ذخیره از JSON استفاده می‌کند نه از فرم.",
    "Paste in a field the form doesn't have.":
        "فیلدی را که در فرم نیست همین‌جا اضافه کنید.",
    "How this server appears in your list. Just for you; it doesn't change how it connects.":
        "اسمی که این سرور در فهرستتان دارد. فقط برای خودتان است و روی نحوه‌ی اتصال اثری ندارد.",
    "\"Berlin, fast\" is easier to find next week than \"server-7\".":
        "«برلین، سریع» را هفته‌ی بعد راحت‌تر از «server-7» پیدا می‌کنید.",
    "The language the server speaks. It must match what the server runs; the form only shows the fields that protocol needs.":
        "زبانی که سرور با آن حرف می‌زند. باید با چیزی که سرور اجرا می‌کند یکی باشد؛ فرم فقط فیلدهای لازمِ همان پروتکل را نشان می‌دهد.",
    "Provider says \"VLESS + Reality\"? Pick vless here.":
        "ارائه‌دهنده گفته «VLESS + Reality»؟ اینجا vless را انتخاب کنید.",
    "The server's address: a domain name or an IP address.":
        "آدرس سرور: یک نام دامنه یا یک آدرس IP.",
    "de1.example.com, exactly as your provider wrote it.":
        "de1.example.com، دقیقاً همان‌طور که ارائه‌دهنده نوشته.",
    "The port the server listens on. 443 is the usual one.":
        "پورتی که سرور رویش گوش می‌دهد. معمولاً 443 است.",
    "443 looks like ordinary web traffic.":
        "پورت 443 شبیه ترافیک عادی وب دیده می‌شود.",
    "Your login on the server: a UUID for VLESS and VMess, the password for Trojan, Shadowsocks and Hysteria2, or your private key for WireGuard.":
        "رمز ورود شما به سرور: برای VLESS و VMess یک UUID، برای Trojan و Shadowsocks و Hysteria2 رمز عبور، و برای WireGuard کلید خصوصی.",
    "Copy it from your provider's page; one wrong character and it won't connect.":
        "از صفحه‌ی ارائه‌دهنده کپی کنید؛ با یک نویسه‌ی اشتباه وصل نمی‌شود.",
    "The server's public key. For Reality it comes from your provider; for WireGuard it is the peer's public key, the other end of the tunnel.":
        "کلید عمومی سرور. برای Reality ارائه‌دهنده می‌دهد؛ برای WireGuard کلید عمومی طرف مقابل است، یعنی آن سرِ تونل.",
    "Paste it exactly as given.":
        "دقیقاً همان‌طور که داده شده بچسبانید.",
    "How VMess scrambles your data. Auto picks a good option for your device.":
        "VMess داده‌های شما را چطور رمزگذاری می‌کند. «auto» گزینه‌ی مناسب دستگاه شما را انتخاب می‌کند.",
    "Leave it on auto unless your provider says otherwise.":
        "مگر ارائه‌دهنده چیز دیگری گفته باشد، روی auto بگذارید.",
    "The encryption method Shadowsocks uses. It must match the server's exactly.":
        "روش رمزگذاری Shadowsocks. باید دقیقاً با سرور یکی باشد.",
    "Pick the same one your server uses, or nothing will load.":
        "همان را بزنید که سرورتان دارد، وگرنه هیچ سایتی باز نمی‌شود.",
    "VLESS's own encryption setting. It is almost always none.":
        "تنظیم رمزگذاری خودِ VLESS. تقریباً همیشه none است.",
    "Leave it as none unless your provider gave you a long string to put here.":
        "مگر ارائه‌دهنده یک رشته‌ی بلند برای اینجا داده باشد، روی none بگذارید.",
    "An optional speed-up mode for VLESS over TLS or Reality, such as xtls-rprx-vision. It must match the server.":
        "حالت اختیاری برای سریع‌تر شدن VLESS روی TLS یا Reality، مثل xtls-rprx-vision. باید با سرور یکی باشد.",
    "Your link says flow=xtls-rprx-vision? Type it here.":
        "توی لینکتان flow=xtls-rprx-vision نوشته؟ همان را اینجا بنویسید.",
    "How data travels to the server: tcp, ws (WebSocket), grpc, xhttp and so on. It must match the server.":
        "داده چطور به سرور می‌رسد: tcp، ws (وب‌سوکت)، grpc، xhttp و غیره. باید با سرور یکی باشد.",
    "A server behind a CDN usually uses ws.":
        "سروری که پشت CDN است معمولاً ws دارد.",
    "The protection layer: none, tls, or reality (looks like a real website).":
        "لایه‌ی محافظ: none، tls یا reality (که شبیه یک سایت واقعی دیده می‌شود).",
    "Your provider mentions Reality? Pick reality.":
        "ارائه‌دهنده اسمی از Reality برده؟ reality را انتخاب کنید.",
    "The website name shown while the secure connection starts (SNI). For Reality, it is the site being imitated.":
        "نام سایتی که موقع شروع اتصال امن نشان داده می‌شود (SNI). در Reality همان سایتی است که تقلید می‌شود.",
    "Copy the sni= value from your link.":
        "مقدار sni= را از لینکتان کپی کنید.",
    "Which browser's handshake style to imitate, such as chrome or firefox. Empty uses the default from Settings.":
        "شروع اتصال را شبیه کدام مرورگر کنم؟ مثلاً chrome یا firefox. اگر خالی بماند، پیش‌فرضِ تنظیمات به کار می‌رود.",
    "chrome blends in with most traffic.":
        "chrome با بیشتر ترافیک‌ها قاطی می‌شود.",
    "The web protocols offered during the handshake, such as h2 or http/1.1. The server must accept them.":
        "پروتکل‌های وبی که موقع شروع اتصال پیشنهاد می‌شوند، مثل h2 یا http/1.1. سرور باید آن‌ها را بپذیرد.",
    "h2,http/1.1 is a safe pair.":
        "h2,http/1.1 یک جفت امن است.",
    "Reality short ID: a short code from your provider that proves you may connect.":
        "شناسه‌ی کوتاه Reality: یک کد کوتاه از ارائه‌دهنده که نشان می‌دهد اجازه‌ی اتصال دارید.",
    "Paste the sid= value from your link.":
        "مقدار sid= را از لینکتان بچسبانید.",
    "Reality spiderX: an optional path used while imitating a site.":
        "spiderX در Reality: یک مسیر اختیاری که موقع تقلید یک سایت استفاده می‌شود.",
    "Usually a single / or empty.":
        "معمولاً فقط یک / یا خالی.",
    "Reality ML-DSA-65 verify key: the server's post-quantum public key, if it has one.":
        "کلید تأیید ML-DSA-65 در Reality: کلید عمومیِ پساکوانتومیِ سرور، اگر داشته باشد.",
    "Only fill this in when your provider hands you one.":
        "فقط وقتی پرش کنید که ارائه‌دهنده یکی به شما داده باشد.",
    "The URL path for WebSocket, HTTP or xhttp connections. It must match the server.":
        "مسیر URL برای اتصال‌های WebSocket، HTTP یا xhttp. باید با سرور یکی باشد.",
    "/ws or /api/v1, as in your link.":
        "/ws یا /api/v1، همان‌طور که در لینکتان است.",
    "The Host header sent with web-style connections. Often the same as the SNI.":
        "هدر Host که همراه اتصال‌های وب‌مانند فرستاده می‌شود. اغلب با SNI یکی است.",
    "Going through a CDN? Put your domain here.":
        "از CDN رد می‌شوید؟ دامنه‌ی خودتان را اینجا بگذارید.",
    "The gRPC service name. It must match the server.":
        "نام سرویس gRPC. باید با سرور یکی باشد.",
    "Copy the serviceName from your link.":
        "مقدار serviceName را از لینکتان کپی کنید.",
    "The SHA-256 fingerprint of the server's certificate, 64 hex characters. When set, only that certificate is trusted, even a self-made one.":
        "اثر انگشت SHA-256 گواهی سرور، 64 نویسه‌ی هگز. اگر پر شود فقط همان گواهی قبول می‌شود، حتی اگر خودساخته باشد.",
    "Pin it when your own server uses a self-signed certificate.":
        "وقتی سرور خودتان گواهی خودامضا دارد، همین را بگذارید.",
    "The password for Hysteria2's salamander obfuscation, which scrambles packets. It must match the server; empty means none.":
        "رمز مبهم‌سازی salamander در Hysteria2 که بسته‌ها را درهم می‌ریزد. باید با سرور یکی باشد؛ خالی یعنی بدون آن.",
    "Your provider's config says obfs: salamander? The password goes here.":
        "در پیکربندی ارائه‌دهنده obfs: salamander نوشته؟ رمزش را اینجا بگذارید.",
    "The address this device gets inside the WireGuard tunnel, such as 10.0.0.2/32. It comes from your provider's config.":
        "آدرسی که این دستگاه داخل تونل WireGuard می‌گیرد، مثل 10.0.0.2/32. از پیکربندی ارائه‌دهنده می‌آید.",
    "Copy the Address line of the WireGuard config.":
        "خط Address را از پیکربندی WireGuard کپی کنید.",
    "An optional extra shared secret. Only needed when your WireGuard config has a PresharedKey.":
        "یک رمز مشترک اضافه که اختیاری است. فقط وقتی لازم است که پیکربندی WireGuard شما PresharedKey داشته باشد.",
    "No PresharedKey in the config? Leave it empty.":
        "در پیکربندی PresharedKey نیست؟ خالی بگذارید.",
    "Three numbers some WireGuard services, like Cloudflare WARP, need, written as 12,34,56.":
        "سه عدد که بعضی سرویس‌های WireGuard، مثل Cloudflare WARP، لازم دارند و به شکل 12,34,56 نوشته می‌شوند.",
    "Your config lists Reserved = 12,34,56? Copy it.":
        "در پیکربندی‌تان Reserved = 12,34,56 نوشته؟ همان را کپی کنید.",
    "Pages stall? Try 1280.":
        "صفحه‌ها گیر می‌کنند؟ 1280 را امتحان کنید.",
    "Seconds between small \"still here\" messages that stop routers from forgetting the tunnel. 0 turns them off.":
        "فاصله‌ی ثانیه‌ای پیام‌های کوچکِ «من هنوز اینجا هستم» که جلوی فراموش شدن تونل در روترها را می‌گیرد. صفر یعنی خاموش.",
    "25 is the usual choice behind a home router.":
        "پشت روتر خانگی معمولاً 25 انتخاب خوبی است.",
    "Dresses plain TCP traffic up as ordinary web requests when set to http. Leave it empty or none for no disguise.":
        "اگر روی http باشد، ترافیک TCP ساده شبیه درخواست‌های معمولی وب می‌شود. خالی یا none یعنی بدون ظاهرسازی.",
    "Your provider's link says headerType=http? Type http.":
        "در لینک ارائه‌دهنده headerType=http نوشته؟ http را بنویسید.",
    "The xhttp style, such as auto, packet-up, stream-up or stream-one. Leave empty unless your provider gives one.":
        "سبک xhttp، مثل auto، packet-up، stream-up یا stream-one. مگر ارائه‌دهنده گفته باشد، خالی بگذارید.",
    "Copy the mode= value from your link.":
        "مقدار mode= را از لینکتان کپی کنید.",
    "Extra xhttp settings written as a JSON object. For advanced setups.":
        "تنظیمات اضافه‌ی xhttp به شکل یک شیء JSON. برای پیکربندی‌های پیشرفته.",
    "Paste the extra block your provider's link carries.":
        "بخش اضافه‌ای را که لینک ارائه‌دهنده دارد همین‌جا بچسبانید.",
    "An Encrypted Client Hello config: hides the website name in the handshake when the server supports it.":
        "پیکربندی Encrypted Client Hello: اگر سرور پشتیبانی کند، نام سایت را در شروع اتصال پنهان می‌کند.",
    "Only fill this in when your provider supplied an ECH string.":
        "فقط وقتی پرش کنید که ارائه‌دهنده رشته‌ی ECH داده باشد.",
    "The certificate name to check, when it differs from the address you connect to.":
        "نامی که باید در گواهی بررسی شود، وقتی با آدرسی که به آن وصل می‌شوید فرق دارد.",
    "The certificate is for a domain, but you connect by IP.":
        "گواهی برای یک دامنه است ولی شما با IP وصل می‌شوید.",
    "Port hopping: a range or list of ports Hysteria2 jumps between to dodge blocking.":
        "پرش پورت: یک بازه یا فهرست از پورت‌ها که Hysteria2 بینشان می‌پرد تا مسدود نشود.",
    "20000-30000 lets it use any port in that range.":
        "20000-30000 یعنی هر پورتی در این بازه.",
    "A shorter interval hops more often, which is harder to block.":
        "فاصله‌ی کوتاه‌تر یعنی پرش بیشتر، و مسدود کردنش سخت‌تر.",
    "Your line uploads at 50 Mbit/s? Enter 50.":
        "خط شما 50 مگابیت بر ثانیه آپلود دارد؟ 50 را بنویسید.",
    "Your line downloads at 200 Mbit/s? Enter 200.":
        "خط شما 200 مگابیت بر ثانیه دانلود دارد؟ 200 را بنویسید.",
    "Example:":
        "مثلاً:",
    "The everyday rules: a few switches for ads, your local network and your country's sites. Edit them on the Routing page.":
        "قوانین روزمره: چند کلید برای تبلیغات، شبکه‌ی محلی و سایت‌های کشور خودتان. از صفحه‌ی مسیریابی ویرایششان کنید.",
    "Good for most days; keep it unless you need something special.":
        "برای بیشتر روزها خوب است؛ مگر کار خاصی داشته باشید، همین را نگه دارید.",
    "Uses the rules in this set of yours instead of the Simple switches. Edit it on the Routing page.":
        "به جای کلیدهای «ساده» از قوانین همین مجموعه‌ی خودتان استفاده می‌کند. از صفحه‌ی مسیریابی ویرایشش کنید.",
    "Pick your movie-night set, then switch back when the credits roll.":
        "مجموعه‌ی «شب فیلم» را بزنید و بعد از تیتراژ پایانی برگردید.",
    "Picks the rules that decide which sites use the tunnel and which go straight out. Simple covers the usual cases; your own rule sets are listed here too.":
        "قوانینی را انتخاب می‌کند که تعیین می‌کنند کدام سایت‌ها از تونل بروند و کدام مستقیم. «ساده» برای معمولی‌ترین حالت‌هاست؛ مجموعه‌های خودتان هم اینجا فهرست می‌شوند.",
    "Switch to your \"Work\" set on office days and back to Simple at home.":
        "روزهای اداری مجموعه‌ی «کار» را بگذارید و در خانه به «ساده» برگردید.",
    "Cuts the start of every secure connection into small pieces so filters can't recognise it. Takes effect when you reconnect.":
        "ابتدای هر اتصال امن را تکه‌تکه می‌کند تا فیلتر نتواند تشخیصش بدهد. بعد از اتصال دوباره اعمال می‌شود.",
    "Servers connect but pages just spin? Switch this on and reconnect.":
        "سرور وصل می‌شود ولی صفحه‌ها فقط می‌چرخند؟ این را روشن کنید و دوباره وصل شوید.",
    "Lets your computer's update and background-report traffic skip the tunnel, so it stops using up the server's data. Those downloads use your normal internet instead.":
        "ترافیک به‌روزرسانی و گزارش پس‌زمینه‌ی کامپیوترتان را از تونل رد نمی‌کند تا حجم سرور را نخورد. آن دانلودها از اینترنت معمولی شما مصرف می‌شوند.",
    "On a server with a monthly data cap, stop Windows updates from eating your gigabytes.":
        "اگر سرورتان حجم ماهانه دارد، نگذارید ویندوز با به‌روزرسانی‌ها گیگابایت‌هایتان را بخورد.",
    "Shows only the servers whose name or address contains what you type. Test works on just the ones shown.":
        "فقط سرورهایی را نشان می‌دهد که نام یا آدرسشان چیزی را که تایپ می‌کنید داشته باشد. «تست» هم فقط روی همین‌ها کار می‌کند.",
    "Type \"de\" to see only your German servers.":
        "«de» را بنویسید تا فقط سرورهای آلمان را ببینید.",
    "Collects the network details the tunnel relies on: server ping, DNS, routes and the latest log lines.":
        "جزئیات شبکه‌ای را که تونل به آن‌ها تکیه دارد جمع می‌کند: پینگ سرور، DNS، مسیرها و آخرین خط‌های لاگ.",
    "Asking for help? Paste this output along with your question.":
        "کمک می‌خواهید؟ این خروجی را همراه سؤالتان بفرستید.",
    "Everything Xray reports, as it happens.":
        "هر چیزی که Xray گزارش می‌دهد، همان لحظه که اتفاق می‌افتد.",
    "Watch it while you connect to see exactly where it stops.":
        "موقع وصل شدن نگاهش کنید تا ببینید دقیقاً کجا گیر می‌کند.",
    "Quick checks: ping, delay and speed.":
        "بررسی‌های سریع: پینگ، تأخیر و سرعت.",
    "Is the slow part the server or your Wi-Fi? Find out in seconds.":
        "مشکل از سرور است یا وای‌فای شما؟ در چند ثانیه می‌فهمید.",
    "The connection's technical details in one place.":
        "جزئیات فنی اتصال، همه در یک جا.",
    "Handy to copy when someone asks \"what does it say?\".":
        "وقتی کسی می‌پرسد «چی نوشته؟» کپی کردنش به کار می‌آید.",
    "The DNS servers that turn website names into addresses, tried in order. Leave it empty to keep the built-in ones.":
        "سرورهای DNS که اسم سایت‌ها را به آدرس تبدیل می‌کنند، به ترتیب امتحان می‌شوند. خالی بگذارید تا همان‌های داخلی برنامه به کار بروند.",
    "Put your favourite first and a backup on the next line.":
        "محبوب‌ترینتان را اول بگذارید و یک پشتیبان در خط بعدی.",
    "Which kinds of address to ask for. UseIPv4 is the safe pick here, because the tunnel can't carry IPv6 and an IPv6 answer would bypass it.":
        "چه نوع آدرسی خواسته شود. UseIPv4 انتخاب امن اینجاست، چون تونل IPv6 را نمی‌برد و جواب IPv6 از تونل رد نمی‌شود.",
    "Sites load on some pages and not others? Try UseIPv4.":
        "بعضی صفحه‌ها باز می‌شوند و بعضی نه؟ UseIPv4 را امتحان کنید.",
    "Fixed answers for names you choose, one per line, written as name = address. They win over any DNS server.":
        "جواب‌های ثابت برای اسم‌هایی که خودتان تعیین می‌کنید، هر خط یکی و به شکل «اسم = آدرس». بر هر سرور DNS اولویت دارند.",
    "Point your home server's name straight at its address.":
        "اسم سرور خانگی‌تان را مستقیم به آدرسش وصل کنید.",
    "DNS servers used only for sites your routing sends direct, so local sites resolve to local addresses.":
        "سرورهای DNS که فقط برای سایت‌هایی به کار می‌روند که مسیریابی مستقیم می‌فرستدشان، تا سایت‌های داخلی به آدرس داخلی برسند.",
    "Your country's sites open faster when a local DNS answers for them.":
        "وقتی یک DNS داخلی جواب بدهد، سایت‌های کشور خودتان سریع‌تر باز می‌شوند.",
    "Clears the domestic DNS, so direct sites use the main list above.":
        "DNS داخلی را خالی می‌کند تا سایت‌های مستقیم از فهرست اصلی بالا استفاده کنند.",
    "Switch it off if a local DNS gives you wrong answers.":
        "اگر یک DNS داخلی جواب‌های غلط می‌دهد، خاموشش کنید.",
    "Sends the DNS questions for sites that use the tunnel through the tunnel too, so your provider can't see or alter them.":
        "پرس‌وجوی DNS سایت‌هایی را که از تونل می‌روند هم از تونل می‌فرستد، تا ارائه‌دهنده‌ی اینترنتتان نتواند ببیندشان یا دستکاری‌شان کند.",
    "Your ISP redirects blocked sites to a warning page? This stops that.":
        "اینترنتتان سایت‌های فیلتر شده را به یک صفحه‌ی هشدار می‌فرستد؟ این جلویش را می‌گیرد.",
    "Asks all the DNS servers at once and takes the first answer, instead of one after another.":
        "از همه‌ی سرورهای DNS هم‌زمان می‌پرسد و اولین جواب را برمی‌دارد، نه یکی‌یکی.",
    "A slow first server stops holding up every page.":
        "اگر سرور اولی کند باشد، دیگر همه‌ی صفحه‌ها منتظرش نمی‌مانند.",
    "Lets Xray reuse a recently expired answer while it fetches a fresh one in the background.":
        "به Xray اجازه می‌دهد جواب تازه‌منقضی‌شده را دوباره به کار ببرد، تا جواب جدید در پس‌زمینه برسد.",
    "Pages start instantly even when the DNS server is slow today.":
        "حتی وقتی امروز سرور DNS کند است، صفحه‌ها فوری شروع می‌شوند.",
    "Your own Xray DNS configuration in JSON. When filled in, it replaces every other DNS setting on this page.":
        "پیکربندی DNS خودتان به شکل JSON برای Xray. اگر پر شود، همه‌ی تنظیمات دیگر DNS این صفحه را کنار می‌زند.",
    "For experts: paste a config someone else tested.":
        "برای حرفه‌ای‌ها: پیکربندی‌ای را که یکی دیگر امتحان کرده بچسبانید.",
    "Shows the rarely needed DNS options.":
        "گزینه‌های DNS را که کمتر لازم می‌شوند نشان می‌دهد.",
    "Skip it until a guide tells you otherwise.":
        "مگر راهنمایی بگوید، سراغش نروید.",
    "Throws away your unsaved edits and goes back to the saved DNS settings.":
        "تغییرات ذخیره‌نشده‌تان را دور می‌ریزد و به تنظیمات DNS ذخیره‌شده برمی‌گردد.",
    "Typed something odd? Revert and start clean.":
        "چیز عجیبی تایپ کردید؟ بازگردانی کنید و از نو شروع کنید.",
    "Checks and saves your DNS settings. If you are connected, reconnect afterwards to use them.":
        "تنظیمات DNS را بررسی و ذخیره می‌کند. اگر وصل هستید، بعدش دوباره وصل شوید تا اعمال شود.",
    "Nothing changes until you press this.":
        "تا این را نزنید هیچ چیز عوض نمی‌شود.",
    "Fills the list below with {name}'s servers. You still need to press Apply.":
        "فهرست پایین را با سرورهای {name} پر می‌کند. هنوز باید «اعمال» را بزنید.",
    "No idea which DNS to trust? Start with a well-known one.":
        "نمی‌دانید به کدام DNS اعتماد کنید؟ با یکی از معروف‌ها شروع کنید.",
    "Fills the domestic DNS with {name}'s addresses. You still need to press Apply.":
        "DNS داخلی را با آدرس‌های {name} پر می‌کند. هنوز باید «اعمال» را بزنید.",
    "A well-known DNS service for sites inside Iran.":
        "یک سرویس DNS شناخته‌شده برای سایت‌های داخل ایران.",
    "What the rule looks for: domains, addresses, ports and so on. Rules are checked from the top, and the first match wins.":
        "قانون دنبال چه می‌گردد: دامنه، آدرس، پورت و غیره. قانون‌ها از بالا به پایین بررسی می‌شوند و اولین موردِ منطبق برنده است.",
    "Put the specific rules above the broad ones.":
        "قانون‌های دقیق را بالاتر از قانون‌های کلی بگذارید.",
    "Tick a rule to use it; untick to keep it without applying it.":
        "تیک بزنید تا قانون به کار برود؛ تیک را بردارید تا بدون اعمال شدن نگه داشته شود.",
    "Pause the streaming rule for a week without losing it.":
        "قانون استریم را یک هفته کنار بگذارید، بی‌آنکه از دستش بدهید.",
    "Your own note about what the rule is for.":
        "یادداشت خودتان درباره‌ی اینکه این قانون برای چیست.",
    "\"Banks stay direct\" beats a rule you can't remember.":
        "«بانک‌ها مستقیم» از قانونی که یادتان نمی‌آید بهتر است.",
    "What happens to traffic that matches: Proxy goes through the tunnel, Direct goes straight out, Block is dropped.":
        "برای ترافیکِ منطبق چه اتفاقی بیفتد: «پروکسی» از تونل می‌رود، «مستقیم» بدون تونل بیرون می‌رود و «مسدود» دور ریخته می‌شود.",
    "Block a tracker, send your own country's sites direct.":
        "یک ردیاب را مسدود کنید و سایت‌های کشور خودتان را مستقیم بفرستید.",
    "Which rules are in charge: Simple, or one of your own rule sets. It's the same choice as the Routing button in the toolbar.":
        "کدام قوانین حاکم باشند: «ساده» یا یکی از مجموعه‌های خودتان. همان انتخابِ دکمه‌ی مسیریابی در نوار بالاست.",
    "Keep a \"Work\" set for office days and flip back to Simple at home.":
        "برای روزهای اداری یک مجموعه‌ی «کار» داشته باشید و در خانه به «ساده» برگردید.",
    "Throws away your unsaved edits and goes back to the saved routing.":
        "تغییرات ذخیره‌نشده را دور می‌ریزد و به مسیریابی ذخیره‌شده برمی‌گردد.",
    "Changed your mind halfway through? Revert and start clean.":
        "وسط کار نظرتان عوض شد؟ بازگردانی کنید و تمیز شروع کنید.",
    "Saves your routing changes. If you are connected, reconnect afterwards to use them.":
        "تغییرات مسیریابی را ذخیره می‌کند. اگر وصل هستید، بعدش دوباره وصل شوید تا اعمال شود.",
    "Edit as much as you like; nothing changes until you press this.":
        "هر قدر دلتان می‌خواهد ویرایش کنید؛ تا این را نزنید چیزی عوض نمی‌شود.",
    "Blocks known ad and tracker domains, so they never load.":
        "دامنه‌های شناخته‌شده‌ی تبلیغات و ردیاب‌ها را مسدود می‌کند تا اصلاً بارگیری نشوند.",
    "Fewer banners, and pages feel lighter.":
        "بنر کمتر، و صفحه‌ها سبک‌تر.",
    "Keeps addresses on your own network, like 192.168.x.x, out of the tunnel.":
        "آدرس‌های شبکه‌ی خودتان، مثل 192.168.x.x، را از تونل بیرون نگه می‌دارد.",
    "Your printer and home router stay reachable while you're connected.":
        "چاپگر و مودم خانه‌تان وقتی وصلید هم در دسترس می‌مانند.",
    "Iranian websites and IP addresses connect directly instead of through the tunnel.":
        "سایت‌ها و آدرس‌های IP ایرانی به‌جای رفتن از تونل مستقیم وصل می‌شوند.",
    "Your bank's site loads as usual while everything else is tunnelled.":
        "سایت بانکتان مثل همیشه باز می‌شود و بقیه از تونل می‌روند.",
    "Russian websites and IP addresses connect directly instead of through the tunnel.":
        "سایت‌ها و آدرس‌های IP روسی به‌جای رفتن از تونل مستقیم وصل می‌شوند.",
    "Local delivery and banking apps keep working like they always did.":
        "برنامه‌های محلی مثل پیک و بانک همان‌طور که همیشه کار می‌کردند کار می‌کنند.",
    "Chinese websites and IP addresses connect directly instead of through the tunnel.":
        "سایت‌ها و آدرس‌های IP چینی به‌جای رفتن از تونل مستقیم وصل می‌شوند.",
    "Local video apps keep loading at full speed.":
        "برنامه‌های ویدیوی محلی با تمام سرعت بارگیری می‌شوند.",
    "Websites that skip the tunnel, one per line. A plain name like example.com also covers its subdomains; groups such as geosite:google work too.":
        "سایت‌هایی که از تونل نمی‌روند، هر خط یکی. یک اسم ساده مثل example.com زیردامنه‌هایش را هم می‌گیرد؛ گروه‌هایی مثل geosite:google هم جواب می‌دهند.",
    "Add your university's site so its library login sees your real address.":
        "سایت دانشگاهتان را اضافه کنید تا ورود به کتابخانه‌اش آدرس واقعی شما را ببیند.",
    "Addresses or ranges that skip the tunnel, one per line. 10.0.0.0/8 covers a whole range at once.":
        "آدرس‌ها یا بازه‌هایی که از تونل نمی‌روند، هر خط یکی. 10.0.0.0/8 یک بازه‌ی کامل را یک‌جا می‌گیرد.",
    "Add your NAS's range so file copies don't crawl through a server abroad.":
        "بازه‌ی NAS خودتان را اضافه کنید تا کپی فایل‌ها از یک سرور آن سر دنیا سینه‌خیز نرود.",
    "Websites to send through the tunnel, one per line. Anything a direct rule above also catches still goes direct.":
        "سایت‌هایی که باید از تونل بروند، هر خط یکی. هر چیزی که یکی از قانون‌های مستقیمِ بالا هم بگیردش، باز مستقیم می‌رود.",
    "List streaming.example.com here to spell out that it should always use the tunnel.":
        "streaming.example.com را اینجا بنویسید تا معلوم باشد همیشه باید از تونل برود.",
    "Your rule sets. Click one to edit it; the active one is chosen at the top of the page.":
        "مجموعه‌قوانین شما. روی یکی کلیک کنید تا ویرایشش کنید؛ مجموعه‌ی فعال بالای صفحه انتخاب می‌شود.",
    "Keep one set per situation and switch with a click.":
        "برای هر موقعیت یک مجموعه داشته باشید و با یک کلیک جابه‌جا شوید.",
    "A blank set; you add every rule yourself.":
        "یک مجموعه‌ی خالی؛ هر قانون را خودتان اضافه می‌کنید.",
    "Start from scratch when you know exactly what you want.":
        "وقتی دقیقاً می‌دانید چه می‌خواهید، از صفر شروع کنید.",
    "Sends everything through the tunnel, except your own local network.":
        "همه‌چیز را از تونل می‌فرستد، به‌جز شبکه‌ی محلی خودتان.",
    "When you want no exceptions at all.":
        "وقتی اصلاً استثنا نمی‌خواهید.",
    "Starts with the same rules the Simple switches make right now.":
        "با همان قانون‌هایی شروع می‌کند که کلیدهای «ساده» همین الان می‌سازند.",
    "Begin from what you have, then add a few special cases.":
        "از چیزی که دارید شروع کنید و چند مورد خاص اضافه کنید.",
    "Downloads a ready-made rule set for Iran from the Chocolate4U project. Needs an internet connection.":
        "یک مجموعه‌ی قوانین آماده برای ایران از پروژه‌ی Chocolate4U دانلود می‌کند. اینترنت لازم دارد.",
    "Iranian sites go direct without you writing a single rule.":
        "سایت‌های ایرانی مستقیم می‌روند، بدون اینکه یک قانون هم بنویسید.",
    "Creates a new rule set from a template.":
        "یک مجموعه‌ی قوانین تازه از روی یک الگو می‌سازد.",
    "Make a \"Movie night\" set in a few clicks.":
        "در چند کلیک یک مجموعه‌ی «شب فیلم» بسازید.",
    "Makes a copy of the selected set.":
        "از مجموعه‌ی انتخاب‌شده یک نسخه می‌سازد.",
    "Try risky changes on a copy and keep the original safe.":
        "تغییرهای پرریسک را روی نسخه‌ی کپی امتحان کنید و اصلی سالم بماند.",
    "Removes the selected rule set.":
        "مجموعه‌ی قوانین انتخاب‌شده را حذف می‌کند.",
    "Clear out the sets you stopped using.":
        "مجموعه‌هایی را که دیگر استفاده نمی‌کنید پاک کنید.",
    "Loads rule sets from a file on your computer.":
        "مجموعه‌های قوانین را از یک فایل روی کامپیوترتان بارگیری می‌کند.",
    "A friend sent you their rules as a file.":
        "دوستتان قانون‌هایش را به‌صورت فایل فرستاده.",
    "Loads rule sets from text you just copied.":
        "مجموعه‌های قوانین را از متنی که همین الان کپی کرده‌اید بارگیری می‌کند.",
    "Copy rules from a chat message, then import them.":
        "قانون‌ها را از یک پیام چت کپی کنید و وارد کنید.",
    "Downloads rule sets from a web address.":
        "مجموعه‌های قوانین را از یک آدرس اینترنتی دانلود می‌کند.",
    "A community list published online? Paste its link.":
        "یک فهرست انجمنی آنلاین منتشر شده؟ لینکش را بچسبانید.",
    "Brings in rule sets made elsewhere.":
        "مجموعه‌های قوانینِی را که جای دیگری ساخته شده وارد می‌کند.",
    "Borrow a tested set instead of writing one.":
        "به‌جای نوشتن، یک مجموعه‌ی امتحان‌شده قرض بگیرید.",
    "Saves the selected set to a file.":
        "مجموعه‌ی انتخاب‌شده را در یک فایل ذخیره می‌کند.",
    "Keep a backup before experimenting.":
        "پیش از آزمایش کردن، یک نسخه‌ی پشتیبان نگه دارید.",
    "Copies the selected set as text you can paste anywhere.":
        "مجموعه‌ی انتخاب‌شده را به شکل متنی کپی می‌کند که هر جا بشود چسباند.",
    "Send your rules to a friend in one message.":
        "قانون‌هایتان را با یک پیام برای دوستتان بفرستید.",
    "Shares the selected rule set with others or saves a copy.":
        "مجموعه‌ی انتخاب‌شده را با دیگران به اشتراک می‌گذارد یا یک نسخه‌اش را ذخیره می‌کند.",
    "Give your setup to someone who just installed sushTun.":
        "تنظیمات خودتان را به کسی بدهید که تازه sushTun را نصب کرده.",
    "The name this set has in the lists.":
        "نامی که این مجموعه در فهرست‌ها دارد.",
    "\"Work\" is easier to find than \"New set 3\".":
        "«کار» از «مجموعه‌ی جدید 3» راحت‌تر پیدا می‌شود.",
    "The rules of this set, checked from the top. The first one that matches decides. Double-click a rule to edit it.":
        "قانون‌های این مجموعه، از بالا به پایین بررسی می‌شوند. اولین موردِ منطبق تصمیم می‌گیرد. برای ویرایش یک قانون روی آن دوبار کلیک کنید.",
    "Block ads first, send local sites direct, tunnel the rest.":
        "اول تبلیغات را مسدود کنید، بعد سایت‌های محلی را مستقیم بفرستید، و بقیه از تونل.",
    "Writes a new rule for this set.":
        "یک قانون تازه برای این مجموعه می‌نویسد.",
    "Send a streaming site through the tunnel.":
        "یک سایت استریم را از تونل بفرستید.",
    "Changes the selected rule.":
        "قانون انتخاب‌شده را تغییر می‌دهد.",
    "Add one more domain to a rule you already made.":
        "یک دامنه‌ی دیگر به قانونی که قبلاً ساخته‌اید اضافه کنید.",
    "Removes the selected rule.":
        "قانون انتخاب‌شده را حذف می‌کند.",
    "That rule that never mattered? Gone.":
        "آن قانونی که هیچ‌وقت به درد نخورد؟ حذف.",
    "Moves the selected rule up. Higher rules are checked first.":
        "قانون انتخاب‌شده را بالا می‌برد. قانون‌های بالاتر زودتر بررسی می‌شوند.",
    "Put \"block ads\" above \"allow everything\".":
        "«مسدود کردن تبلیغات» را بالاتر از «اجازه به همه‌چیز» بگذارید.",
    "Moves the selected rule down. Lower rules are checked later.":
        "قانون انتخاب‌شده را پایین می‌برد. قانون‌های پایین‌تر دیرتر بررسی می‌شوند.",
    "Let a general rule wait until the special ones had their turn.":
        "بگذارید قانون کلی صبر کند تا نوبت قانون‌های خاص تمام شود.",
    "How domain names are matched against address rules. Inherit uses the global choice; the others decide when a name is looked up to get its IP.":
        "اینکه اسم دامنه‌ها چطور با قانون‌های آدرسی تطبیق داده شوند. «به ارث بردن» انتخاب کلی را به کار می‌برد؛ بقیه تعیین می‌کنند اسم چه موقع برای پیدا کردن IP جست‌وجو شود.",
    "Leave it on Inherit unless a rule with IP addresses misses its target.":
        "مگر اینکه قانونی که آدرس IP دارد به هدفش نخورد، روی «به ارث بردن» بگذارید.",
    "Shows the rarely needed options.":
        "گزینه‌هایی را که کمتر لازم می‌شوند نشان می‌دهد.",
    "On":
        "روشن",
    "A few easy switches for the usual cases.":
        "چند کلید ساده برای حالت‌های معمول.",
    "Most people never need more than this tab.":
        "بیشتر آدم‌ها هیچ‌وقت بیشتر از این برگه لازم ندارند.",
    "Build your own sets of rules, one rule at a time.":
        "مجموعه‌های قوانینِ خودتان را بسازید، قانون به قانون.",
    "A set for streaming nights, another for work.":
        "یک مجموعه برای شب‌های استریم، یکی برای کار.",
    "Cleanup tools for the server list.":
        "ابزارهای پاکسازی برای فهرست سرورها.",
    "Tidy up after a big import in two clicks.":
        "بعد از یک ورود حجیم، با دو کلیک مرتب کنید.",
    "Changes this subscription's name, address, update schedule and filter.":
        "نام، آدرس، برنامه‌ی به‌روزرسانی و فیلتر این اشتراک را تغییر می‌دهد.",
    "Provider moved to a new address? Paste it here.":
        "ارائه‌دهنده آدرس جدید گرفته؟ همین‌جا بچسبانید.",
    "Downloads this subscription's server list again right now.":
        "فهرست سرورهای این اشتراک را همین الان دوباره دانلود می‌کند.",
    "New servers announced? Don't wait for the schedule.":
        "سرور تازه اعلام شده؟ منتظر برنامه نمانید.",
    "Removes this subscription and the servers it brought. You are asked first.":
        "این اشتراک و سرورهایی را که آورده حذف می‌کند. اول از شما می‌پرسد.",
    "Cancelled with that provider? Clear out their servers in one go.":
        "اشتراکتان با آن ارائه‌دهنده تمام شده؟ سرورهایش را یک‌جا پاک کنید.",
    "Downloads every enabled subscription again right now.":
        "همه‌ی اشتراک‌های فعال را همین الان دوباره دانلود می‌کند.",
    "Monday morning: refresh all your lists in one click.":
        "صبح دوشنبه: همه‌ی فهرست‌هایتان را با یک کلیک تازه کنید.",
    "Adds a subscription: a web address that hands out a list of servers. sushTun downloads it now and keeps it updated.":
        "یک اشتراک اضافه می‌کند: آدرسی اینترنتی که فهرستی از سرورها می‌دهد. sushTun همین الان دانلودش می‌کند و به‌روز نگهش می‌دارد.",
    "Your provider gave you one link instead of fifty? This is where it goes.":
        "ارائه‌دهنده به‌جای پنجاه لینک یک لینک داده؟ جایش اینجاست.",
    "Matches BitTorrent traffic.":
        "ترافیک BitTorrent را می‌گیرد.",
    "Block torrents on a server with a data cap.":
        "روی سروری که حجم دارد، تورنت را مسدود کنید.",
    "Matches plain, unencrypted web traffic.":
        "ترافیک ساده و رمزنشده‌ی وب را می‌گیرد.",
    "Catch the old sites that still don't use HTTPS.":
        "آن سایت‌های قدیمی را که هنوز HTTPS ندارند بگیرید.",
    "Matches encrypted connections, which is nearly all modern web traffic.":
        "اتصال‌های رمزشده را می‌گیرد، که تقریباً همه‌ی ترافیک امروزی وب است.",
    "Catch every secure connection, whatever the website.":
        "هر اتصال امن را بگیرید، هر سایتی که باشد.",
    "Your own note about what this rule is for.":
        "یادداشت خودتان درباره‌ی اینکه این قانون برای چیست.",
    "Traffic that matches goes through the tunnel.":
        "ترافیکِ منطبق از تونل می‌رود.",
    "A site that's blocked where you live.":
        "سایتی که جایی که شما هستید مسدود است.",
    "Traffic that matches skips the tunnel and goes straight out.":
        "ترافیکِ منطبق از تونل نمی‌رود و مستقیم بیرون می‌رود.",
    "Your bank, which dislikes foreign addresses.":
        "بانکتان، که از آدرس‌های خارجی خوشش نمی‌آید.",
    "Traffic that matches is dropped and goes nowhere.":
        "ترافیکِ منطبق دور ریخته می‌شود و به جایی نمی‌رسد.",
    "Ads, trackers, and that one app that phones home.":
        "تبلیغات، ردیاب‌ها، و آن یک برنامه‌ای که مدام به خانه زنگ می‌زند.",
    "Websites to match, one per line. domain:example.com covers a site and its subdomains, full: an exact name, keyword: any name containing a word, geosite: a ready-made group.":
        "سایت‌های موردنظر، هر خط یکی. domain:example.com یک سایت و زیردامنه‌هایش را می‌گیرد، full: یک اسم دقیق، keyword: هر اسمی که فلان کلمه را داشته باشد و geosite: یک گروه آماده.",
    "geosite:google matches Google's whole family of sites.":
        "geosite:google کل خانواده‌ی سایت‌های گوگل را می‌گیرد.",
    "Addresses to match, one per line. A range like 10.0.0.0/8 covers many at once, and geoip:ir covers a whole country.":
        "آدرس‌های موردنظر، هر خط یکی. بازه‌ای مثل 10.0.0.0/8 چندین آدرس را یک‌جا می‌گیرد و geoip:ir کل یک کشور را.",
    "192.168.0.0/16 matches everything on a typical home network.":
        "192.168.0.0/16 همه‌ی دستگاه‌های یک شبکه‌ی خانگی معمولی را می‌گیرد.",
    "Only match traffic going to these ports: one port, a range, or a comma-separated list.":
        "فقط ترافیکی که به این پورت‌ها می‌رود: یک پورت، یک بازه یا فهرستی با ویرگول.",
    "80,443 matches ordinary web browsing.":
        "80,443 گشت‌وگذار معمولی در وب را می‌گیرد.",
    "Only match this kind of traffic. TCP covers most things; UDP covers calls, games and QUIC.":
        "فقط همین نوع ترافیک را بگیرد. TCP بیشتر چیزها را می‌پوشاند؛ UDP تماس‌ها، بازی‌ها و QUIC را.",
    "Leave it on Any unless the rule is only for one of them.":
        "مگر قانون فقط برای یکی از آن‌هاست، روی «هر» بگذارید.",
    "Names of programs to match, one per line, such as firefox. Works on Linux and Windows.":
        "اسم برنامه‌هایی که باید گرفته شوند، هر خط یکی، مثل firefox. روی لینوکس و ویندوز کار می‌کند.",
    "Name your download manager here and choose Direct to keep it off the tunnel.":
        "اسم برنامه‌ی دانلودتان را اینجا بنویسید و «مستقیم» را انتخاب کنید تا از تونل دور بماند.",
    "Shows the rarely needed conditions.":
        "شرط‌هایی را که کمتر لازم می‌شوند نشان می‌دهد.",
    "Skip it for simple rules.":
        "برای قانون‌های ساده سراغش نروید.",
    "The server's protocol, such as vless, vmess or trojan.":
        "پروتکل سرور، مثل vless، vmess یا trojan.",
    "Handy when a provider says \"use a Trojan server\".":
        "وقتی ارائه‌دهنده می‌گوید «یک سرور Trojan بگیرید» به درد می‌خورد.",
    "A dot marks the server Connect will use.":
        "یک نقطه نشان می‌دهد «اتصال» از کدام سرور استفاده می‌کند.",
    "Not sure which one is live? Look for the dot.":
        "مطمئن نیستید کدام یکی فعال است؟ دنبال نقطه بگردید.",
    "The server's name. Double-click a row to edit it.":
        "اسم سرور. برای ویرایش روی یک ردیف دوبار کلیک کنید.",
    "Rename \"server-7\" to \"Berlin, fast\" so you know it next week.":
        "«server-7» را به «برلین، سریع» تغییر بدهید تا هفته‌ی بعد بشناسیدش.",
    "How long the server took to answer in the last test. Lower is better; click the header to sort.":
        "سرور در آخرین تست چقدر طول کشید جواب بدهد. هرچه کمتر بهتر؛ برای مرتب کردن روی عنوان کلیک کنید.",
    "Under 300 ms feels snappy, over 800 ms feels like wading through honey.":
        "زیر 300 میلی‌ثانیه روان است، بالای 800 مثل راه رفتن توی عسل.",
    "How the server's traffic is carried and protected, such as tcp/reality or ws/tls.":
        "ترافیک سرور چطور حمل و محافظت می‌شود، مثل tcp/reality یا ws/tls.",
    "If one transport is blocked on your network, try a server with another.":
        "اگر یک نوع انتقال در شبکه‌ی شما مسدود است، سروری با نوع دیگر را امتحان کنید.",
    "The subscription the server came from, or a dash if you added it yourself.":
        "اشتراکی که سرور از آن آمده، یا یک خط تیره اگر خودتان اضافه‌اش کرده‌اید.",
    "Find every server one provider gave you.":
        "همه‌ی سرورهایی را که یک ارائه‌دهنده به شما داده پیدا کنید.",
    "Active":
        "فعال",
    "The language of the app.":
        "زبان برنامه.",
    "Prefer to read it in فارسی? Change it here.":
        "ترجیح می‌دهید همه‌چیز را به فارسی بخوانید؟ از همین‌جا عوضش کنید.",
    "Everyday basics: how delays are measured, the log level and update checks.":
        "مسائل پایه‌ی روزمره: تأخیر چطور اندازه‌گیری شود، سطح لاگ و بررسی به‌روزرسانی.",
    "Check here whether a newer version is out.":
        "همین‌جا ببینید نسخه‌ی تازه‌ای آمده یا نه.",
    "Tricks that make your traffic harder for filters to spot or slow down.":
        "ترفندهایی که تشخیص یا کند کردن ترافیک شما را برای فیلتر سخت‌تر می‌کنند.",
    "Connected but nothing loads? Start here.":
        "وصل هستید ولی هیچ‌چیز باز نمی‌شود؟ از اینجا شروع کنید.",
    "The proxy port other programs can use, and whether other devices may share it.":
        "پورت پروکسی‌ای که برنامه‌های دیگر می‌توانند استفاده کنند، و اینکه آیا دستگاه‌های دیگر هم می‌توانند از آن استفاده کنند.",
    "Let your phone borrow the tunnel.":
        "بگذارید گوشی‌تان تونل را قرض بگیرد.",
    "The country and website lists that routing relies on, and how they stay fresh.":
        "فهرست‌های کشور و سایت که مسیریابی به آن‌ها تکیه دارد، و اینکه چطور تازه بمانند.",
    "A site is routed wrongly? Update these lists.":
        "یک سایت اشتباه مسیریابی می‌شود؟ این فهرست‌ها را به‌روز کنید.",
    "The name and password of the Wi-Fi hotspot that shares the tunnel.":
        "نام و رمز هات‌اسپات وای‌فایی که تونل را به اشتراک می‌گذارد.",
    "Pick a name your guests will recognise.":
        "اسمی بگذارید که مهمان‌هایتان بشناسند.",
    "What happens when you turn on your computer.":
        "وقتی کامپیوترتان را روشن می‌کنید چه اتفاقی بیفتد.",
    "Have sushTun waiting in the tray before you open a browser.":
        "قبل از اینکه مرورگر را باز کنید، sushTun توی سینی منتظرتان باشد.",
    "One local port where each username leaves through a different server.":
        "یک پورت محلی که هر نام کاربری از طریق یک سرور متفاوت بیرون می‌رود.",
    "Two browsers, two countries, at the same time.":
        "دو مرورگر، دو کشور، هم‌زمان.",
    "Local ports that always lead to one fixed address.":
        "پورت‌های محلی که همیشه به یک آدرس ثابت می‌رسند.",
    "Reach your home server's SSH from anywhere.":
        "از هر جا به SSH سرور خانگی‌تان برسید.",
    "Save your servers and settings to a file, or load them back.":
        "سرورها و تنظیماتتان را در یک فایل ذخیره کنید، یا دوباره بارگیری کنید.",
    "Moving to a new computer? Start here.":
        "به کامپیوتر جدید می‌روید؟ از اینجا شروع کنید.",
    "The address the Ping tool contacts to check that the internet itself is reachable.":
        "آدرسی که ابزار «پینگ» برای بررسی در دسترس بودن خودِ اینترنت به آن وصل می‌شود.",
    "Prefer something close to home? Put your ISP's address here.":
        "یک آدرس نزدیک‌تر می‌خواهید؟ آدرس ISP خودتان را بگذارید.",
    "Comparing your numbers with v2rayN? Keep Round trip.":
        "اعدادتان را با v2rayN مقایسه می‌کنید؟ «رفت‌وبرگشت» را نگه دارید.",
    "How many seconds the Throughput and Baseline tools watch the tunnel before reporting.":
        "ابزارهای «توان عبوری» و «خط پایه» چند ثانیه تونل را زیر نظر بگیرند و بعد گزارش بدهند.",
    "A bursty connection? A longer sample gives a steadier number.":
        "اینترنت‌تان ناپایدار است؟ نمونه‌ی طولانی‌تر عدد پایدارتری می‌دهد.",
    "MTU is the largest packet the tunnel sends. A lower value leaves room for the extra wrapping a tunnel adds; 1420 works almost everywhere.":
        "MTU بزرگ‌ترین بسته‌ای است که تونل می‌فرستد. مقدار کمتر جا برای بسته‌بندی اضافه‌ای که تونل می‌کند باز می‌گذارد؛ 1420 تقریباً همه‌جا خوب جواب می‌دهد.",
    "Small pages load but big ones stall? Try 1380.":
        "صفحه‌های کوچک باز می‌شوند ولی بزرگ‌ها گیر می‌کنند؟ 1380 را امتحان کنید.",
    "How much detail Xray writes to the log. Warning stays quiet; debug is very chatty.":
        "Xray چقدر جزئیات در لاگ بنویسد. «warning» ساکت است؛ «debug» بسیار پرحرف.",
    "Chasing a problem? Raise it for a while, then put it back.":
        "دنبال یک مشکل می‌گردید؟ مدتی بالاترش ببرید و بعد برش گردانید.",
    "Looks for a new sushTun version now and then, and lets you know when there is one.":
        "هر از گاهی دنبال نسخه‌ی تازه‌ی sushTun می‌گردد و اگر باشد خبرتان می‌کند.",
    "Never miss the fix for last week's annoying bug.":
        "حتماً اصلاحیه‌ی باگ آزاردهنده‌ی هفته‌ی پیش را از دست ندهید.",
    "Looks for a new version right now.":
        "همین الان دنبال نسخه‌ی تازه می‌گردد.",
    "Just heard about a release? Don't wait, check.":
        "تازه خبر یک نسخه‌ی جدید را شنیده‌اید؟ صبر نکنید، بررسی کنید.",
    "The version you are running, and a button to check for a newer one.":
        "نسخه‌ای که اجرا می‌کنید، و دکمه‌ای برای بررسی نسخه‌ی جدیدتر.",
    "Handy to mention when you report a problem.":
        "وقتی مشکلی را گزارش می‌دهید ذکرش به کار می‌آید.",
    "Cuts the start of every secure (TLS) connection into small pieces so filters can't recognise it. Works with TLS and Reality servers over TCP.":
        "ابتدای هر اتصال امن (TLS) را تکه‌تکه می‌کند تا فیلتر نتواند تشخیصش بدهد. با سرورهای TLS و Reality روی TCP کار می‌کند.",
    "Servers connect but pages won't load? Try this first.":
        "سرور وصل می‌شود ولی صفحه‌ها باز نمی‌شوند؟ اول این را امتحان کنید.",
    "Which packets to cut up: tlshello is the secure handshake's opening message, or a range like 1-3 for the first few packets.":
        "کدام بسته‌ها تکه شوند: tlshello پیام آغازین اتصال امن است، یا یک بازه مثل 1-3 برای چند بسته‌ی اول.",
    "The default tlshello is right for nearly everyone.":
        "مقدار پیش‌فرض tlshello برای تقریباً همه خوب است.",
    "How big each piece is, in bytes. A range such as 100-200 picks a random size each time.":
        "هر تکه چند بایت باشد. بازه‌ای مثل 100-200 هر بار یک اندازه‌ی تصادفی برمی‌دارد.",
    "Still blocked? Try smaller pieces, like 10-30.":
        "هنوز مسدود است؟ تکه‌های کوچک‌تر را امتحان کنید، مثلاً 10-30.",
    "The pause between pieces, in milliseconds. A range such as 10-20 picks a random pause each time.":
        "مکث بین تکه‌ها، به میلی‌ثانیه. بازه‌ای مثل 10-20 هر بار یک مکث تصادفی برمی‌دارد.",
    "Too slow to connect? Shorten the pause.":
        "وصل شدن خیلی طول می‌کشد؟ مکث را کوتاه‌تر کنید.",
    "The most pieces one message may be cut into. 0 means no limit.":
        "حداکثر تعداد تکه‌هایی که یک پیام می‌تواند به آن‌ها بریده شود. صفر یعنی بدون محدودیت.",
    "Leave it at 0 unless a guide gives you a number.":
        "مگر راهنمایی عددی بدهد، روی صفر بگذارید.",
    "Carries many connections inside one connection to the server, which saves set-up time. It is skipped for servers that use a flow such as Vision.":
        "چندین اتصال را داخل یک اتصال به سرور می‌برد و در زمان برقراری صرفه‌جویی می‌کند. برای سرورهایی که flow دارند، مثل Vision، کنار گذاشته می‌شود.",
    "Pages with dozens of small files can open noticeably faster.":
        "صفحه‌هایی که ده‌ها فایل کوچک دارند می‌توانند محسوساً سریع‌تر باز شوند.",
    "How many connections may share one tunnel connection.":
        "چند اتصال می‌توانند یک اتصال تونل را با هم استفاده کنند.",
    "Lower it if one slow download holds everything else up.":
        "اگر یک دانلود کند بقیه را معطل می‌کند، کمترش کنید.",
    "The same idea for UDP traffic, such as calls and games: how many UDP sessions share one connection.":
        "همین ایده برای ترافیک UDP، مثل تماس‌ها و بازی‌ها: چند نشست UDP یک اتصال را با هم استفاده کنند.",
    "Voice calls stutter? Try a smaller number.":
        "صدای تماس‌ها قطع‌وصل می‌شود؟ عدد کوچک‌تری را امتحان کنید.",
    "What to do with UDP traffic on port 443 (QUIC, used by HTTP/3): reject it so apps fall back to normal TCP, allow it, or skip the multiplexing for it.":
        "با ترافیک UDP روی پورت 443 (QUIC که HTTP/3 استفاده می‌کند) چه شود: ردش کند تا برنامه‌ها به TCP معمولی برگردند، اجازه بدهد، یا چندگانه‌سازی را برایش کنار بگذارد.",
    "Browsers retry over TCP when it is rejected, which is usually the smoothest.":
        "وقتی رد شود، مرورگرها با TCP دوباره تلاش می‌کنند، که معمولاً روان‌ترین حالت است.",
    "Lets the first data travel with the connection request, saving one back-and-forth when connecting to the server.":
        "اجازه می‌دهد اولین داده همراه درخواست اتصال برود و یک رفت‌وبرگشت موقع وصل شدن به سرور کم شود.",
    "Shaves a little off the wait for every new page.":
        "از انتظار برای هر صفحه‌ی تازه کمی کم می‌کند.",
    "Lets one connection use several network paths at once, such as Wi-Fi and cable, when your system and the server both support it.":
        "یک اتصال می‌تواند هم‌زمان از چند مسیر شبکه، مثل وای‌فای و کابل، استفاده کند، به شرطی که سیستم و سرور هر دو پشتیبانی کنند.",
    "Wi-Fi and a cable both up? If one drops, the connection carries on.":
        "هم وای‌فای وصل است هم کابل؟ اگر یکی قطع شود، اتصال ادامه پیدا می‌کند.",
    "Sends a few random packets before a Hysteria2 connection starts, to blur its first moments. Other server types ignore it.":
        "پیش از شروع اتصال Hysteria2 چند بسته‌ی تصادفی می‌فرستد تا لحظه‌های اول آن محو شود. انواع دیگر سرور نادیده‌اش می‌گیرند.",
    "A Hysteria2 server that gets blocked at the first packet? Try it.":
        "سرور Hysteria2 همان اولین بسته مسدود می‌شود؟ امتحانش کنید.",
    "How big each random packet is, in bytes. A range such as 10-20 picks a random size each time.":
        "هر بسته‌ی تصادفی چند بایت باشد. بازه‌ای مثل 10-20 هر بار یک اندازه‌ی تصادفی برمی‌دارد.",
    "Leave it alone unless a guide suggests a value.":
        "مگر راهنمایی مقداری پیشنهاد کند، دستش نزنید.",
    "The pause after each random packet, in milliseconds. A range such as 10-16 picks a random pause each time.":
        "مکث بعد از هر بسته‌ی تصادفی، به میلی‌ثانیه. بازه‌ای مثل 10-16 هر بار یک مکث تصادفی برمی‌دارد.",
    "Longer pauses make the connection slower to start.":
        "مکث‌های طولانی‌تر شروع اتصال را کندتر می‌کنند.",
    "Opens one local port where the username you log in with decides which of your servers the connection leaves from.":
        "یک پورت محلی باز می‌کند که نام کاربری‌ای که با آن وارد می‌شوید تعیین می‌کند اتصال از کدام یک از سرورهایتان بیرون برود.",
    "Browser A as \"germany\", browser B as \"japan\": two countries at the same time.":
        "مرورگر A با نام «germany» و مرورگر B با «japan»: دو کشور هم‌زمان.",
    "The local port apps connect to for the multi-exit proxy.":
        "پورت محلی‌ای که برنامه‌ها برای پروکسی چندخروجی به آن وصل می‌شوند.",
    "Pick a free one above 1024 if the default is already taken.":
        "اگر پورت پیش‌فرض اشغال است، یک پورت آزاد بالای 1024 بردارید.",
    "The password apps send along with their username. Required, because the username only means something with a login.":
        "رمزی که برنامه‌ها همراه نام کاربری می‌فرستند. الزامی است، چون نام کاربری فقط وقتی معنا دارد که ورود وجود داشته باشد.",
    "Keep the generated one; you'll paste it into your apps anyway.":
        "همان رمز ساخته‌شده را نگه دارید؛ به هر حال باید در برنامه‌هایتان بچسبانیدش.",
    "Shows or hides the password.":
        "رمز را نشان می‌دهد یا پنهان می‌کند.",
    "Peek at it, then hide it again.":
        "یک نگاه بهش بیندازید و دوباره پنهانش کنید.",
    "Adds a username and the server it should use.":
        "یک نام کاربری و سروری را که باید استفاده کند اضافه می‌کند.",
    "Add \"germany\" and pick your Frankfurt server.":
        "«germany» را اضافه کنید و سرور فرانکفورتتان را انتخاب کنید.",
    "The username apps log in with to use this exit.":
        "نام کاربری‌ای که برنامه‌ها برای استفاده از این خروجی با آن وارد می‌شوند.",
    "Something short you will remember, like \"germany\".":
        "چیزی کوتاه که یادتان بماند، مثل «germany».",
    "The server this username's connections leave from.":
        "سروری که اتصال‌های این نام کاربری از آن بیرون می‌روند.",
    "Frankfurt for \"germany\", Tokyo for \"japan\".":
        "فرانکفورت برای «germany»، توکیو برای «japan».",
    "Deletes this username and its server choice.":
        "این نام کاربری و سروری را که برایش انتخاب شده حذف می‌کند.",
    "Retire an exit you no longer use.":
        "خروجی‌ای را که دیگر استفاده نمی‌کنید کنار بگذارید.",
    "The Wi-Fi name other devices see when they look for the hotspot.":
        "اسم وای‌فایی که دستگاه‌های دیگر وقتی دنبال هات‌اسپات می‌گردند می‌بینند.",
    "Something friendly like \"Living room\".":
        "یک اسم دوستانه مثل «اتاق نشیمن».",
    "Makes a new random password. Devices already connected will need the new one next time.":
        "یک رمز تصادفی تازه می‌سازد. دستگاه‌هایی که الان وصل‌اند دفعه‌ی بعد رمز جدید را لازم دارند.",
    "Someone you don't know joined? Change it.":
        "کسی را که نمی‌شناسید وصل شد؟ رمز را عوض کنید.",
    "The password other devices type to join the hotspot. It needs at least 8 characters.":
        "رمزی که دستگاه‌های دیگر برای وصل شدن به هات‌اسپات وارد می‌کنند. دست‌کم 8 نویسه لازم است.",
    "Press New for a random one and read it off to your guests.":
        "«جدید» را بزنید تا رمز تصادفی بگیرید و برای مهمان‌هایتان بخوانیدش.",
    "Check it before reading it out loud.":
        "پیش از خواندنش با صدای بلند، یک نگاه بهش بیندازید.",
    "How the hotspot's Wi-Fi is protected. WPA2 works with nearly every device; WPA3 is newer and stronger but older devices can't join.":
        "وای‌فای هات‌اسپات چطور محافظت شود. WPA2 تقریباً با همه‌ی دستگاه‌ها کار می‌کند؛ WPA3 تازه‌تر و قوی‌تر است ولی دستگاه‌های قدیمی نمی‌توانند وصل شوند.",
    "Old tablet won't connect? Choose WPA2.":
        "تبلت قدیمی وصل نمی‌شود؟ WPA2 را انتخاب کنید.",
    "Which Wi-Fi band the hotspot uses. 2.4 GHz reaches farther; 5 GHz is faster over a short distance.":
        "هات‌اسپات از کدام باند وای‌فای استفاده کند. 2.4 گیگاهرتز بردش بیشتر است؛ 5 گیگاهرتز در فاصله‌ی کم سریع‌تر است.",
    "Phone in the next room? 2.4 GHz. Sitting beside it? 5 GHz.":
        "گوشی در اتاق بغلی است؟ 2.4 گیگاهرتز. کنارش نشسته‌اید؟ 5 گیگاهرتز.",
    "Adds a local port that always leads to one fixed address.":
        "یک پورت محلی اضافه می‌کند که همیشه به یک آدرس ثابت می‌رسد.",
    "Make port 2222 lead to your home server's SSH.":
        "پورت 2222 را به SSH سرور خانگی‌تان وصل کنید.",
    "The port on this computer that apps connect to.":
        "پورتی روی این کامپیوتر که برنامه‌ها به آن وصل می‌شوند.",
    "Connect to localhost:2222 and the forward does the rest.":
        "به localhost:2222 وصل شوید و بقیه‌اش را انتقال پورت انجام می‌دهد.",
    "The address and port the forward leads to, as host:port.":
        "آدرس و پورتی که این انتقال به آن می‌رسد، به شکل host:port.",
    "home.example.com:22 for SSH to your home server.":
        "home.example.com:22 برای SSH به سرور خانگی‌تان.",
    "Whether the connection to the target goes through the tunnel or straight out from your computer.":
        "اتصال به مقصد از تونل برود یا مستقیم از کامپیوتر شما بیرون بزند.",
    "Through the tunnel to reach a server that only your VPN can see.":
        "از تونل، تا به سروری برسید که فقط VPN شما آن را می‌بیند.",
    "Which kind of traffic the forward carries. TCP suits most things such as SSH and websites; UDP suits calls and games.":
        "این انتقال چه نوع ترافیکی را حمل کند. TCP برای بیشتر کارها مثل SSH و وب مناسب است؛ UDP برای تماس‌ها و بازی‌ها.",
    "SSH and web servers use TCP.":
        "SSH و سرورهای وب از TCP استفاده می‌کنند.",
    "Untick to pause this forward without deleting it.":
        "تیک را بردارید تا این انتقال بی‌آنکه حذف شود متوقف شود.",
    "Switch the SSH forward off for the weekend.":
        "انتقال SSH را برای آخر هفته خاموش کنید.",
    "Your phone on the same Wi-Fi can reach it through this computer's address.":
        "گوشی‌تان روی همان وای‌فای از آدرس این کامپیوتر به آن می‌رسد.",
    "Deletes this forward.":
        "این انتقال را حذف می‌کند.",
    "Tidy up forwards you no longer need.":
        "انتقال‌هایی را که دیگر لازم ندارید مرتب کنید.",
    "The local port where programs can reach the tunnel as a SOCKS5 proxy on 127.0.0.1.":
        "پورت محلی‌ای که برنامه‌ها می‌توانند از طریق آن به تونل، به‌عنوان یک پروکسی SOCKS5 روی 127.0.0.1، برسند.",
    "Point a browser or download manager at 127.0.0.1 and this port.":
        "مرورگر یا برنامه‌ی دانلودتان را روی 127.0.0.1 و همین پورت تنظیم کنید.",
    "Lets other devices on your network use this proxy too. Set a user and password below so strangers can't.":
        "اجازه می‌دهد دستگاه‌های دیگر شبکه هم از این پروکسی استفاده کنند. پایین‌تر نام کاربری و رمز بگذارید تا غریبه‌ها نتوانند.",
    "Your phone on the same Wi-Fi can borrow the tunnel.":
        "گوشی‌تان روی همان وای‌فای می‌تواند تونل را قرض بگیرد.",
    "A username that other devices must give. It only counts when a password is set too.":
        "نام کاربری‌ای که دستگاه‌های دیگر باید بدهند. فقط وقتی به حساب می‌آید که رمز هم گذاشته باشید.",
    "Anything simple, like \"family\".":
        "هر چیز ساده‌ای، مثل «family».",
    "The password that goes with the username. Without both, anyone on your network can use the proxy.":
        "رمزی که با نام کاربری می‌آید. اگر هر دو نباشند، هر کسی در شبکه‌تان می‌تواند از پروکسی استفاده کند.",
    "Pick one you'd be happy to read out to a houseguest.":
        "رمزی بگذارید که بتوانید راحت برای مهمان خانه بخوانید.",
    "Peeks at the start of a connection to learn the website's name, so name-based routing rules still work when an app connects by number.":
        "ابتدای هر اتصال را نگاه می‌کند تا اسم سایت را بفهمد، تا قانون‌های بر پایه‌ی اسم وقتی برنامه با عدد وصل می‌شود هم کار کنند.",
    "Needed for \"send this site direct\" to work with every app.":
        "برای اینکه «این سایت مستقیم برود» با همه‌ی برنامه‌ها جواب بدهد لازم است.",
    "Uses the discovered name only to choose the route, and still connects to the address the app asked for.":
        "اسم کشف‌شده را فقط برای انتخاب مسیر به کار می‌برد و باز هم به آدرسی که برنامه خواسته وصل می‌شود.",
    "Handy if a game or app breaks when its destination is rewritten.":
        "اگر بازی یا برنامه‌ای با عوض شدن مقصدش خراب می‌شود به کار می‌آید.",
    "Which browser's way of starting a secure connection to imitate, for servers that don't pick one themselves. Off leaves it as is.":
        "شروع اتصال امن را شبیه کدام مرورگر کند، برای سرورهایی که خودشان انتخاب نمی‌کنند. «خاموش» یعنی دست نمی‌زند.",
    "Blocked for looking unlike a browser? Try chrome.":
        "به‌خاطر شبیه مرورگر نبودن مسدود می‌شوید؟ chrome را امتحان کنید.",
    "Where the country and website lists used by routing come from.":
        "فهرست‌های کشور و سایتی که مسیریابی استفاده می‌کند از کجا می‌آیند.",
    "Chocolate4U (Iran) has extra lists made for Iranian sites.":
        "Chocolate4U (Iran) فهرست‌های اضافه‌ای برای سایت‌های ایرانی دارد.",
    "Downloads fresh country and website lists now.":
        "فهرست‌های تازه‌ی کشور و سایت را همین الان دانلود می‌کند.",
    "A site is routed wrongly? Update the lists, then reconnect.":
        "یک سایت اشتباه مسیریابی می‌شود؟ فهرست‌ها را به‌روز کنید و دوباره وصل شوید.",
    "Downloads fresh country and website lists now, and shows when they were last updated.":
        "فهرست‌های تازه‌ی کشور و سایت را همین الان دانلود می‌کند و نشان می‌دهد آخرین بار کی به‌روز شده‌اند.",
    "How often the lists refresh by themselves. Off means only when you press Update now.":
        "فهرست‌ها هر چند وقت یک‌بار خودشان تازه شوند. «خاموش» یعنی فقط وقتی «به‌روزرسانی اکنون» را بزنید.",
    "24 refreshes them once a day.":
        "عدد 24 یعنی روزی یک‌بار.",
    "Starts hidden in the tray instead of opening its window.":
        "به‌جای باز کردن پنجره، پنهان در سینی شروع می‌شود.",
    "It runs quietly until you need it.":
        "بی‌صدا کار می‌کند تا وقتی که لازمش داشته باشید.",
    "Connects to your active server as soon as sushTun starts.":
        "به محض شروع sushTun به سرور فعال شما وصل می‌شود.",
    "Turn on your computer and you're protected before the browser opens.":
        "کامپیوتر را روشن می‌کنید و پیش از باز شدن مرورگر محافظت شده‌اید.",
    "Saves your servers, subscriptions and settings to one file.":
        "سرورها، اشتراک‌ها و تنظیمات شما را در یک فایل ذخیره می‌کند.",
    "Moving to a new computer? Take this file with you.":
        "به کامپیوتر جدید می‌روید؟ این فایل را با خودتان ببرید.",
    "Loads a backup file and replaces your current servers and settings with what it holds.":
        "یک فایل پشتیبان را بارگیری می‌کند و سرورها و تنظیمات فعلی شما را با چیزی که در آن است جایگزین می‌کند.",
    "Fresh install? Restore and everything is back.":
        "نصب تازه؟ بازیابی کنید و همه‌چیز برمی‌گردد.",
    "The language of the app's menus and messages. Persian also flips the layout to right-to-left.":
        "زبان منوها و پیام‌های برنامه. فارسی چیدمان را هم راست‌به‌چپ می‌کند.",
    "Switch to فارسی and everything reads from the right.":
        "به فارسی که بروید، همه‌چیز از راست خوانده می‌شود.",
    "The method your system uses to decide how fast to send data on the link to the server. System default is the safe choice.":
        "روشی که سیستم شما برای تصمیم‌گیری درباره‌ی سرعتِ فرستادن داده روی خط اتصال به سرور استفاده می‌کند. «پیش‌فرض سیستم» انتخاب امن است.",
    "On a long, lossy link, bbr can help keep speeds up.":
        "روی یک خط طولانی و پرافت، bbr می‌تواند به حفظ سرعت کمک کند.",
    "The hotspot stops announcing its name, so devices must type it in to join.":
        "هات‌اسپات دیگر اسمش را اعلام نمی‌کند، پس دستگاه‌ها باید اسم را دستی وارد کنند.",
    "Keeps it out of the neighbours' Wi-Fi list.":
        "از فهرست وای‌فای همسایه‌ها بیرونش نگه می‌دارد.",
    "Devices on the hotspot can reach the internet but not each other.":
        "دستگاه‌های روی هات‌اسپات به اینترنت می‌رسند ولی به هم نه.",
    "Guests share your connection without seeing each other's phones.":
        "مهمان‌ها از اتصال شما استفاده می‌کنند بی‌آنکه گوشی‌های همدیگر را ببینند.",
    "Opens sushTun by itself whenever you sign in to your computer.":
        "هر بار که وارد کامپیوترتان می‌شوید، sushTun خودش باز می‌شود.",
    "Boot up and it is already waiting in the tray.":
        "کامپیوتر را روشن می‌کنید و sushTun از قبل توی سینی منتظر است.",
    "Shares the tunnel with other devices through a Wi-Fi hotspot, so they need no setup. It starts when you connect; the name and password are in Settings.":
        "تونل را از طریق یک هات‌اسپات وای‌فای با دستگاه‌های دیگر به اشتراک می‌گذارد تا نیازی به تنظیم نداشته باشند. وقتی وصل می‌شوید شروع می‌شود؛ نام و رمزش در تنظیمات است.",
    "A friend's phone needs the tunnel? Let it join your laptop's hotspot.":
        "گوشی دوستتان به تونل نیاز دارد؟ بگذارید به هات‌اسپات لپ‌تاپتان وصل شود.",
    "Your list of servers: pick one, test how fast they are, and connect.":
        "فهرست سرورهایتان: یکی را انتخاب کنید، سرعتشان را تست کنید و وصل شوید.",
    "Twenty servers and no idea which one? Start here.":
        "بیست سرور دارید و نمی‌دانید کدام؟ از اینجا شروع کنید.",
    "Links that keep your server list up to date by themselves.":
        "لینک‌هایی که فهرست سرورهایتان را خودکار به‌روز نگه می‌دارند.",
    "Your provider adds new servers every month? A subscription fetches them for you.":
        "ارائه‌دهنده‌تان هر ماه سرور تازه می‌گذارد؟ اشتراک آن‌ها را برایتان می‌آورد.",
    "Decide which sites go through the tunnel and which go straight out.":
        "تعیین کنید کدام سایت‌ها از تونل بروند و کدام مستقیم بیرون بزنند.",
    "Keep your local bank direct and everything else tunnelled.":
        "بانک محلی‌تان را مستقیم نگه دارید و بقیه را از تونل بفرستید.",
    "Choose who looks up website addresses for you.":
        "انتخاب کنید چه کسی آدرس سایت‌ها را برایتان پیدا کند.",
    "Sites won't open but the connection is fine? A different DNS can help.":
        "سایت‌ها باز نمی‌شوند ولی اتصال سالم است؟ یک DNS دیگر می‌تواند کمک کند.",
    "The live log, handy tools and diagnostics.":
        "لاگ زنده، ابزارهای کاربردی و عیب‌یابی.",
    "Something odd? Look here before asking anyone for help.":
        "چیزی عجیب است؟ قبل از اینکه از کسی کمک بخواهید اینجا را ببینید.",
    "Opens the settings: startup, local proxy, anti-filter tricks, language and more.":
        "تنظیمات را باز می‌کند: شروع به کار، پروکسی محلی، ترفندهای ضدفیلتر، زبان و بیشتر.",
    "Want sushTun to start with your computer? It's in there.":
        "می‌خواهید sushTun همراه کامپیوترتان روشن شود؟ همان‌جاست.",
    "Pings your active server and the internet address from Settings (Ping target) and shows the replies.":
        "سرور فعال شما و آدرس اینترنتی تنظیمات (هدف پینگ) را پینگ می‌کند و جواب‌ها را نشان می‌دهد.",
    "Is it the server or your Wi-Fi? Compare the two lines.":
        "مشکل از سرور است یا وای‌فای شما؟ دو خط را با هم مقایسه کنید.",
    "Opens a few plain connections to the active server and shows the average, fastest and slowest time.":
        "چند اتصال ساده به سرور فعال باز می‌کند و میانگین، سریع‌ترین و کندترین زمان را نشان می‌دهد.",
    "Pages feel sluggish? See whether the server itself is the slow part.":
        "صفحه‌ها کند شده‌اند؟ ببینید خودِ سرور بخش کند ماجراست یا نه.",
    "Measures the tunnel's real traffic for a few seconds, so start a download first.":
        "ترافیک واقعی تونل را چند ثانیه اندازه می‌گیرد، پس اول یک دانلود شروع کنید.",
    "Start a big download, press this, and read your true speed.":
        "یک دانلود بزرگ شروع کنید، این را بزنید و سرعت واقعی‌تان را بخوانید.",
    "Compares your real network adapter with the tunnel over a few seconds. Windows only.":
        "کارت شبکه‌ی واقعی شما را با تونل در چند ثانیه مقایسه می‌کند. فقط ویندوز.",
    "Curious how much the tunnel costs you in speed? This tells you.":
        "کنجکاوید تونل چقدر از سرعتتان کم می‌کند؟ این می‌گوید.",
    "Adds servers: paste a link or a subscription address, a config, or load a QR image.":
        "سرور اضافه می‌کند: یک لینک یا آدرس اشتراک، یک پیکربندی بچسبانید یا یک عکس QR بارگیری کنید.",
    "A friend sent you a vless:// link? Paste it here and you're done.":
        "دوستتان یک لینک vless:// فرستاده؟ همین‌جا بچسبانید و کار تمام است.",
    "Checks how quickly the servers in the list answer and fills the Delay column. While it runs, this button becomes Cancel.":
        "سرعت جواب دادن سرورهای فهرست را می‌سنجد و ستون «تأخیر» را پر می‌کند. وقتی در حال اجراست، این دکمه به «لغو» تبدیل می‌شود.",
    "Back from a trip? Re-test to see which servers still work.":
        "از سفر برگشته‌اید؟ دوباره تست کنید ببینید کدام سرورها هنوز کار می‌کنند.",
    "Loads a small page through each server, like a real visit. Slower, but it shows what you will actually get.":
        "از هر سرور یک صفحه‌ی کوچک بارگیری می‌کند، مثل یک بازدید واقعی. کندتر است ولی نشان می‌دهد در عمل چه گیرتان می‌آید.",
    "A server that answers ping yet won't open pages? This catches it.":
        "سروری که به پینگ جواب می‌دهد ولی صفحه‌ای باز نمی‌کند؟ این پیدایش می‌کند.",
    "Only checks that each server's port answers, without loading anything. Quick, but it can't tell whether the server really works.":
        "فقط بررسی می‌کند پورت هر سرور جواب بدهد، بی‌آنکه چیزی بارگیری شود. سریع است ولی نمی‌تواند بگوید سرور واقعاً کار می‌کند یا نه.",
    "Hundreds of servers? Ping them first to weed out the dead ones.":
        "صدها سرور دارید؟ اول پینگشان کنید تا سرورهای مرده کنار بروند.",
    "Switches to the server with the lowest delay in your last test. Run Test first, otherwise there is nothing to compare.":
        "به سروری که در آخرین تست کمترین تأخیر را داشت می‌رود. اول «تست» را اجرا کنید، وگرنه چیزی برای مقایسه نیست.",
    "Twenty servers and no idea which one? One click picks the quickest.":
        "بیست سرور دارید و نمی‌دانید کدام؟ با یک کلیک سریع‌ترین انتخاب می‌شود.",
    "Deletes the servers whose last test failed, except the active one. You are asked first.":
        "سرورهایی را که آخرین تستشان ناموفق بود حذف می‌کند، به‌جز سرور فعال. اول از شما می‌پرسد.",
    "Imported 80 servers and half are dead? Test, then sweep them away.":
        "80 سرور وارد کردید و نصفشان مرده؟ تست کنید، بعد جارو کنید.",
    "Deletes extra copies of the same server (same protocol, address, port and ID) and keeps one. You are asked first.":
        "نسخه‌های اضافه‌ی یک سرور (با پروتکل، آدرس، پورت و شناسه‌ی یکسان) را حذف می‌کند و یکی را نگه می‌دارد. اول از شما می‌پرسد.",
    "Imported the same subscription twice? This tidies up.":
        "یک اشتراک را دوبار وارد کرده‌اید؟ این مرتبش می‌کند.",
    "Loads a small page through the selected server(s) and times it.":
        "از سرورهای انتخاب‌شده یک صفحه‌ی کوچک بارگیری می‌کند و زمانش را می‌گیرد.",
    "Select your three favourites and see which one is quickest today.":
        "سه سرور محبوبتان را انتخاب کنید و ببینید امروز کدام سریع‌تر است.",
    "Only checks that the selected server(s) answer, without loading anything.":
        "فقط بررسی می‌کند سرورهای انتخاب‌شده جواب بدهند، بی‌آنکه چیزی بارگیری شود.",
    "A quick \"is it even awake?\" check.":
        "یک بررسی سریع که «اصلاً بیدار است؟»",
    "Removes the selected server(s) from your list.":
        "سرورهای انتخاب‌شده را از فهرستتان حذف می‌کند.",
    "Get rid of the ones that never worked.":
        "آن‌هایی را که هیچ‌وقت کار نکردند دور بریزید.",
    "Makes this the server that Connect uses.":
        "این را همان سروری می‌کند که «اتصال» از آن استفاده می‌کند.",
    "Found a quick one? Set it active, then connect.":
        "یک سرور سریع پیدا کردید؟ فعالش کنید و بعد وصل شوید.",
    "Opens this server's details so you can change them.":
        "جزئیات این سرور را باز می‌کند تا تغییرشان بدهید.",
    "Fix a typo in the name, or swap in a new port.":
        "غلط املایی اسم را درست کنید یا یک پورت تازه بگذارید.",
    "Makes a copy you can tweak without touching the original.":
        "یک نسخه می‌سازد که بدون دست زدن به اصلی بشود تغییرش داد.",
    "Try a different port on a copy, and keep the working one safe.":
        "پورت دیگری را روی نسخه‌ی کپی امتحان کنید و نسخه‌ی سالم را نگه دارید.",
    "Puts this server's link on your clipboard. Anyone who has it can use the server, so share it with care.":
        "لینک این سرور را در کلیپ‌بورد می‌گذارد. هر کسی که لینک را داشته باشد می‌تواند از سرور استفاده کند، پس با احتیاط بفرستیدش.",
    "Paste it into a chat to give a friend the same server.":
        "آن را در یک چت بچسبانید تا همان سرور را به یک دوست بدهید.",
    "Shows this server's link as a QR code another phone can scan.":
        "لینک این سرور را به‌شکل یک کد QR نشان می‌دهد که گوشی دیگری می‌تواند اسکنش کند.",
    "Set up your phone by pointing its camera at the screen.":
        "دوربین گوشی را روی صفحه بگیرید و گوشی‌تان تنظیم می‌شود.",
    "Shows or hides the {column} column.":
        "ستون «{column}» را نشان می‌دهد یا پنهان می‌کند.",
    "Too cluttered? Hide what you never look at.":
        "شلوغ است؟ آنچه هیچ‌وقت نگاه نمی‌کنید پنهان کنید.",

    # -- main_window.py -------------------------------------------------
    "Restored leftover network settings from a previous session.":
        "تنظیمات شبکه باقی‌مانده از نشست قبلی بازگردانی شد.",
    "Could not restore leftover network settings: {error}":
        "بازگردانی تنظیمات شبکه باقی‌مانده ممکن نشد: {error}",
    "Could not refresh the login task: {error}": "به‌روزرسانی وظیفه ورود ممکن نشد: {error}",
    "Auto-connect skipped: no server selected.": "اتصال خودکار نادیده گرفته شد: سروری انتخاب نشده.",
    "Auto-connect: waiting for network to reach {name}…":
        "اتصال خودکار: در انتظار شبکه برای رسیدن به {name}…",
    "Auto-connect failed: {error}": "اتصال خودکار ناموفق بود: {error}",
    "no active internet interface": "هیچ رابط اینترنتی فعالی وجود ندارد",
    "Test failed: {error}": "تست ناموفق بود: {error}",
    "Test finished.": "تست تمام شد.",
    "Connect": "اتصال",
    "Disconnect": "قطع اتصال",
    "Restore network": "بازگردانی شبکه",
    "Low usage": "مصرف کم",
    "Share via hotspot": "اشتراک با هات‌اسپات",
    "Not available on this platform yet.": "هنوز روی این پلتفرم در دسترس نیست.",
    "Route devices on this PC's Windows hotspot through the tunnel, "
    "so phones need no setup of their own.":
        "دستگاه‌های متصل به هات‌اسپات ویندوز این رایانه را از طریق تونل عبور بده، "
        "تا گوشی‌ها نیازی به تنظیم جداگانه نداشته باشند.",
    "Start a Wi-Fi hotspot whose devices use the tunnel, so phones need "
    "no setup of their own. Its name and password appear in the log.":
        "یک هات‌اسپات Wi-Fi راه‌اندازی کن که دستگاه‌هایش از تونل استفاده کنند، تا گوشی‌ها نیازی "
        "به تنظیم جداگانه نداشته باشند. نام و رمز آن در گزارش نمایش داده می‌شود.",
    "Reconnect now": "اتصال دوباره",
    "Live log": "گزارش زنده",
    "Tools": "ابزارها",
    "macOS cannot run a Wi-Fi hotspot while it is itself on Wi-Fi. To share the tunnel, "
    "turn on Settings → Local proxy → Allow other devices on your network, and set this "
    "Mac as the proxy on the other device.":
        "macOS وقتی خودش به Wi-Fi وصل است نمی‌تواند هات‌اسپات Wi-Fi بسازد. برای اشتراک تونل، "
        "تنظیمات ← پروکسی محلی ← «اجازه به دستگاه‌های دیگر در شبکه شما» را روشن کنید و این Mac را "
        "به‌عنوان پروکسی در دستگاه دیگر تنظیم کنید.",
    "Not running as administrator — connecting will fail.":
        "به‌عنوان مدیر اجرا نشده — اتصال با خطا مواجه خواهد شد.",
    "macOS privacy protection kept the administrator copy of sushTun out of this folder "
    "(Desktop, Documents and Downloads are protected). Move sushTun to Applications or "
    "another folder and open it again.":
        "حفاظت از حریم خصوصی macOS اجازه نداد نسخهٔ مدیر sushTun به این پوشه دسترسی داشته باشد "
        "(Desktop، Documents و Downloads محافظت‌شده‌اند). sushTun را به Applications یا پوشهٔ "
        "دیگری منتقل کنید و دوباره باز کنید.",
    "Show": "نمایش",
    "Quit": "خروج",
    "Delete {n} server(s)?": "{n} سرور حذف شود؟",
    "Active server changed": "سرور فعال تغییر کرد",
    "Clipboard has no importable server link.": "کلیپ‌بورد شامل لینک قابل‌وارد‌کردنی نیست.",
    "Imported {n} server(s).": "{n} سرور وارد شد.",
    "Active server set to {name}": "سرور فعال روی {name} تنظیم شد",
    "Active server set to {name}.": "سرور فعال روی {name} تنظیم شد.",
    "Remove {n} failed server(s)?": "{n} سرور ناموفق حذف شود؟",
    "No failed servers to remove.": "سرور ناموفقی برای حذف وجود ندارد.",
    "Remove {n} duplicate server(s)?": "{n} سرور تکراری حذف شود؟",
    "No duplicate servers to remove.": "سرور تکراری‌ای برای حذف وجود ندارد.",
    "Refreshing {name}…": "در حال به‌روزرسانی {name}…",
    "Subscription refresh failed: {error}": "به‌روزرسانی اشتراک ناموفق بود: {error}",
    "Subscription updated.": "اشتراک به‌روزرسانی شد.",
    "Delete subscription and its profiles?": "اشتراک و سرورهای آن حذف شود؟",
    "No enabled subscriptions to update.": "اشتراک فعالی برای به‌روزرسانی وجود ندارد.",
    "Updating 0 of {n} subscriptions…": "در حال به‌روزرسانی 0 از {n} اشتراک…",
    "Update all failed: {error}": "به‌روزرسانی همه ناموفق بود: {error}",
    "Updated {n} of {total} subscriptions.": "{n} از {total} اشتراک به‌روزرسانی شد.",
    "First error: {error}": "اولین خطا: {error}",
    "sushTun {tag} is available": "نسخه {tag} از sushTun در دسترس است",
    "No profile": "بدون سرور",
    "Import or select a profile first.": "ابتدا یک سرور وارد کنید یا انتخاب کنید.",
    "Working…": "در حال انجام…",
    "RUNNING": "در حال اجرا",
    "STOPPED": "متوقف شده",
    "{items} changed": "{items} تغییر کرد",
    "Log level": "سطح لاگ",
    "Core options": "گزینه‌های هسته",
    "Geo data updated": "داده‌های جغرافیایی به‌روزرسانی شد",
    "Settings restored from backup": "تنظیمات از نسخه پشتیبان بازیابی شد",
    "Routing saved": "مسیریابی ذخیره شد",
    "DNS saved": "DNS ذخیره شد",
    "Low usage on": "مصرف کم روشن",
    "Low usage off": "مصرف کم خاموش",
    "Anti-filter on": "ضدفیلتر روشن",
    "Anti-filter off": "ضدفیلتر خاموش",
    "Routing changed": "مسیریابی تغییر کرد",
    "Geo data updated.": "داده‌های جغرافیایی به‌روزرسانی شد.",
    "Hotspot sharing off.": "اشتراک‌گذاری هات‌اسپات خاموش شد.",
    "Hotspot sharing on — it starts when you connect.":
        "اشتراک‌گذاری هات‌اسپات روشن شد — با اتصال بعدی راه می‌افتد.",
    "Starting the hotspot…": "در حال روشن کردن هات‌اسپات…",
    "Hotspot is on.": "هات‌اسپات روشن است.",
    "Hotspot could not start: {error}": "هات‌اسپات روشن نشد: {error}",
    "Still running here. Quit from this icon's menu, or press Ctrl+Q.":
        "همچنان در حال اجراست. از منوی این آیکون خارج شوید یا Ctrl+Q را بزنید.",

    # -- dialogs.py: SettingsDialog language ---------------------------------
    "Language": "زبان",
    "Restart sushTun to apply the new language.": "برای اعمال زبان جدید، sushTun را دوباره اجرا کنید.",

    # -- standard QDialogButtonBox text, overridden explicitly -------------
    "Save": "ذخیره",
    "OK": "تأیید",

    # -- core/connection.py's on_step callback (ui/main_window.py._on_step) --
    # A small, fixed set of the (English-only, core/ stays that way) step
    # strings connection.py emits -- tr() translates these known ones and
    # falls back to English for any dynamic one (an interface name, an
    # exception message) it has never seen.
    "Experimental platform (Linux) — network backend is unverified.":
        "پلتفرم آزمایشی (Linux) — باطن شبکه تأیید نشده است.",
    "Detecting active interface...": "در حال شناسایی رابط فعال...",
    "Backing up DNS...": "در حال پشتیبان‌گیری از DNS...",
    "Building runtime config...": "در حال ساخت پیکربندی اجرایی...",
    "Starting Xray...": "در حال اجرای Xray...",
    "Waiting for TUN adapter...": "در انتظار آداپتور TUN...",
    "Configuring tunnel adapter...": "در حال پیکربندی آداپتور تونل...",
    "Routing DNS and traffic through the tunnel...": "در حال مسیریابی DNS و ترافیک از طریق تونل...",
    "WARNING: DNS could not be routed through the tunnel — "
    "lookups will leave unencrypted via the local network.":
        "هشدار: DNS نتوانست از طریق تونل مسیریابی شود — "
        "درخواست‌ها به‌صورت رمزنگاری‌نشده از شبکه محلی خارج می‌شوند.",
    "Connected.": "متصل شد.",
    "Starting Windows hotspot...": "در حال راه‌اندازی هات‌اسپات ویندوز...",
    "Hotspot settings applied.": "تنظیمات هات‌اسپات اعمال شد.",
    "WARNING: Windows kept its own hotspot name and password.":
        "هشدار: ویندوز نام و رمز هات‌اسپات خودش را نگه داشت.",
    "Starting Wi-Fi hotspot...": "در حال راه‌اندازی هات‌اسپات Wi-Fi...",
    "Gateway mode on — hotspot clients now use the tunnel.":
        "حالت دروازه روشن است — کلاینت‌های هات‌اسپات اکنون از تونل استفاده می‌کنند.",
    "Building runtime config (macOS: SOCKS + tun2socks bridge)...":
        "در حال ساخت پیکربندی اجرایی (macOS: پل SOCKS + tun2socks)...",
    "Starting tun2socks bridge...": "در حال اجرای پل tun2socks...",
    "Previous session left DNS pointing at 127.0.0.1. Restoring...":
        "نشست قبلی DNS را روی 127.0.0.1 رها کرده بود. در حال بازگردانی...",
    "Disconnecting...": "در حال قطع اتصال...",
    "Network restored.": "شبکه بازگردانی شد.",
    "Tunnel DNS was cleared by another program — restored.":
        "DNS تونل توسط برنامه دیگری پاک شده بود — بازگردانی شد.",
    "WARNING: tunnel DNS was cleared by another program and could not "
    "be restored — lookups are leaving outside the tunnel.":
        "هشدار: DNS تونل توسط برنامه دیگری پاک شد و بازگردانی نشد — "
        "درخواست‌ها بیرون از تونل خارج می‌شوند.",

    # -- missed on the first pass, caught by test_i18n_coverage.py ----------
    "XUDP concurrency": "هم‌روندی XUDP",
    "Allow other devices on your network": "اجازه به دستگاه‌های دیگر در شبکه شما",
    "Routing": "مسیریابی",
    "{what} — reconnect to apply.": "{what} — برای اعمال، دوباره متصل شوید.",
    # -- ui/update_dialog + General: in-app update --------------------------
    "Update sushTun": "به‌روزرسانی sushTun",
    "Download and install": "دانلود و نصب",
    "You have version {version}.": "نسخه‌ی فعلی شما {version} است.",
    "No release notes.": "توضیحاتی برای این نسخه ثبت نشده است.",
    "What's new": "تازه‌ها",
    "Download progress": "پیشرفت دانلود",
    "Later": "بعداً",
    "Open the download page": "باز کردن صفحه‌ی دانلود",
    "This copy can't update itself. Download {version} and replace "
    "it by hand.":
        "این نسخه نمی‌تواند خودش را به‌روزرسانی کند. {version} را دانلود کنید "
        "و دستی جایگزین کنید.",
    "Couldn't open a browser. The page is {url}":
        "مرورگر باز نشد. نشانی صفحه: {url}",
    "You opened sushTun {this}, but another copy is already running — the "
    "window on screen is that one. Quit it first, then open this copy again.":
        "شما sushTun {this} را باز کردید، ولی نسخه‌ی دیگری از قبل در حال اجراست — "
        "پنجره‌ای که می‌بینید مال آن است. اول آن را ببندید، بعد این نسخه را باز کنید.",
    "You opened sushTun {this}, but sushTun {running} is already running — the "
    "window on screen is that one. Quit it first, then open this copy again.":
        "شما sushTun {this} را باز کردید، ولی sushTun {running} از قبل در حال اجراست — "
        "پنجره‌ای که می‌بینید مال آن است. اول آن را ببندید، بعد این نسخه را باز کنید.",
    "Stopping…": "در حال توقف…",
    "Downloading {name}…": "در حال دانلود {name}…",
    "Downloaded {done} of {total}": "{done} از {total} دانلود شد",
    "Downloaded {done}": "{done} دانلود شد",
    "Update cancelled.": "به‌روزرسانی لغو شد.",
    "Update failed: {error}": "به‌روزرسانی ناموفق بود: {error}",
    "unknown error": "خطای ناشناخته",
    "Try again": "تلاش دوباره",
    "Downloaded and checked. sushTun will close to finish.":
        "دانلود و بررسی شد. sushTun برای تکمیل بسته می‌شود.",
    "Restart and install": "راه‌اندازی دوباره و نصب",
    "Installing…": "در حال نصب…",
    "Check now": "بررسی کن",
    "Checking…": "در حال بررسی…",
    "Could not reach GitHub.": "دسترسی به GitHub ممکن نشد.",
    "You're up to date.": "شما به‌روز هستید.",
    "Version {version}": "نسخه {version}",

    # -- first-run tour -----------------------------------------------------
    "Put servers in a row so your traffic hops through each one.":
        "چند سرور را پشت سر هم بگذارید تا ترافیکتان از هرکدام یکی‌یکی عبور کند.",
    "A relay inside the country, then a server abroad.":
        "اول یک رله داخل کشور، بعد یک سرور در خارج.",
    "Skip": "رد کردن",
    "Back": "قبلی",
    "Next": "بعدی",
    "Welcome to sushTun": "به sushTun خوش آمدید",
    "sushTun sends your computer's internet through a server you choose, so blocked sites open and your traffic stays private. Let's take a quick look around.":
        "sushTun اینترنت کامپیوترتان را از سروری که خودتان انتخاب می‌کنید رد می‌کند؛ پس سایت‌های بسته باز می‌شوند و ترافیکتان خصوصی می‌ماند. بیایید یک نگاه سریع بیندازیم.",
    "Add your servers": "سرورهایتان را اضافه کنید",
    "Copy a server link or your provider's subscription URL, then press Import. Ctrl+V works too. A link looks like vless://…":
        "لینک یک سرور یا آدرس اشتراکی را که ارائه‌دهنده‌تان داده کپی کنید و «وارد کردن» را بزنید. Ctrl+V هم جواب می‌دهد. لینک‌ها شبیه vless://… هستند.",
    "Your server list": "فهرست سرورها",
    "Press Test to see each server's ping and the flag of the country it really exits from. Then pick the one you like.":
        "«تست» را بزنید تا پینگ هر سرور و پرچم کشوری را که واقعاً از آن بیرون می‌روید ببینید. بعد هرکدام را که خواستید انتخاب کنید.",
    "One click puts every app on your computer on the tunnel.":
        "با یک کلیک، همه‌ی برنامه‌های کامپیوترتان از تونل رد می‌شوند.",
    "Routing mode": "حالت مسیریابی",
    "Choose what goes through the tunnel. For example: Iranian sites open directly, everything else goes through the tunnel.":
        "تعیین کنید چه چیزهایی از تونل رد شوند. مثلاً سایت‌های ایرانی مستقیم باز شوند و بقیه از تونل بروند.",
    "A server connects but nothing loads? Switch this on, then reconnect.":
        "سرور وصل می‌شود ولی چیزی باز نمی‌شود؟ این را روشن کنید و دوباره وصل شوید.",
    "Put servers in a row so your traffic hops through each one. Test tells you where you exit and which link breaks.":
        "چند سرور را پشت سر هم بگذارید تا ترافیکتان از هرکدام یکی‌یکی عبور کند. با «تست» می‌فهمید از کجا بیرون می‌روید و کدام حلقه مشکل دارد.",
    "Share the tunnel with your phone: turn this on and join your computer's Wi-Fi hotspot.":
        "تونل را با گوشی‌تان شریک شوید: این را روشن کنید و گوشی را به هات‌اسپات وای‌فای کامپیوترتان وصل کنید.",
    "You're all set": "همه‌چیز آماده است",
    "Hover anything: every control explains itself. You can replay this tour from Settings → General.":
        "ماوس را روی هر چیزی نگه دارید، خودش توضیح می‌دهد. این راهنما را هر وقت خواستید از تنظیمات ← عمومی دوباره ببینید.",
    "Welcome tour": "راهنمای شروع",
    "Show the tour again": "نمایش دوباره‌ی راهنما",
    "Starts when you close Settings": "با بستن تنظیمات شروع می‌شود",
    "Replays the short walk through the app that you saw on first launch. It starts when you close Settings.":
        "همان گشت کوتاهی را که بار اول دیدید دوباره نشان می‌دهد. با بستن تنظیمات شروع می‌شود.",
    "Showing sushTun to a friend? Replay it for them.":
        "می‌خواهید sushTun را به دوستتان نشان بدهید؟ راهنما را برایش دوباره پخش کنید.",

    # -- ui/a-foundation: connection header ----------------------------------
    "Connected": "متصل",
    "Disconnected": "قطع شده",
    "Down / Up": "دانلود / آپلود",
    "This session": "این نشست",
    "More connection actions": "گزینه‌های بیشتر اتصال",

    # -- ui/a-pages: embeddable routing/dns pages ----------------------------
    "Apply": "اعمال",
    "Revert": "بازگردانی",
    "Move rule up": "انتقال قانون به بالا",
    "Move rule down": "انتقال قانون به پایین",
    "New set": "مجموعه جدید",
    "Apply changes?": "اعمال تغییرات؟",
    "Discard": "نادیده‌گرفتن",
    "You have unsaved changes.": "تغییرات ذخیره‌نشده دارید.",

    # -- ui/a-foundation: reconnect-notice wording ------------------------
    # Technical acronyms that stay Latin inside the Persian sentence, so
    # the coverage test sees them mapped.
    "MTU": "MTU",

    # -- ui/a-shell: sidebar window ----------------------------------------
    "Filter…": "فیلتر…",
    "DNS": "DNS",
    "Activity": "فعالیت",
    "Hotspot": "هات‌اسپات",
    "SSID: {ssid} · Password: {pwd}":
        "SSID: {ssid} · رمز عبور: {pwd}",
    "Connected · {server}": "متصل · {server}",
    "off": "خاموش",
    # -- ui/a-pages-main -----------------------------------------------------
    "More server actions": "گزینه‌های بیشتر سرور",
    "Import…": "وارد کردن…",
    "Delete subscription": "حذف اشتراک",

    # -- ui/a-dialogs --------------------------------------------------------
    "Refresh": "بازخوانی",
    "0 uses the app-wide refresh interval.":
        "۰ یعنی از بازه به‌روزرسانی کلی برنامه استفاده شود.",
    "Regex. Only servers whose name matches are kept.":
        "عبارت باقاعده (regex). فقط سرورهایی که نامشان جور باشد نگه داشته می‌شوند.",

    # -- ui/a-settings: System Settings style settings window ----------------
    # New footnote for "Split the TLS handshake" Switch
    "Try this if servers connect but sites won't load.": "اگر سرورها متصل می‌شوند اما سایت‌ها باز نمی‌شوند این را امتحان کنید.",
    # Divider footnote under TLS fragment fields
    "Applies to TLS and Reality servers over TCP. The speed test uses it too, so servers that only work with it don't show as failed.":
        "برای سرورهای TLS و Reality برروی TCP اعمال می‌شود. تست سرعت هم از آن استفاده می‌کند، بنابراین سرورهایی که فقط با این کار می‌کنند به‌عنوان ناموفق نشان داده نمی‌شوند.",
    # Parameterized validation messages (different from dialogs.py which uses QMessageBox)
    "Validation failed: {err}": "بررسی ناموفق بود: {err}",
    "Settings invalid: {err}": "تنظیمات نامعتبر است: {err}",
    "Startup setting failed: {err}": "تنظیم راه‌اندازی ناموفق بود: {err}",
    # Sidebar labels and titles new to the settings window
    "General": "عمومی",
    "Split the TLS handshake": "تقسیم دست‌دهی TLS",
    "XUDP UDP443": "XUDP UDP443",
    "Backup": "پشتیبان‌گیری",
    "Done": "انجام",

    # -- ui/a-dialogs: empty server list -------------------------------------
    "No servers yet. Import a link, or add a subscription.":
        "هنوز سروری نیست. یک لینک وارد کنید یا یک اشتراک اضافه کنید.",
    "No servers match the filter.": "هیچ سروری با این فیلتر پیدا نشد.",

    # -- ui/a-shell: TCP tuning ---------------------------------------------
    "TCP Fast Open": "TCP Fast Open",
    "Saves a round trip when opening connections.":
        "باز کردن اتصال‌ها را یک رفت‌وبرگشت سریع‌تر می‌کند.",
    "Multipath TCP": "Multipath TCP",
    "Falls back to normal TCP if the system can't use it.":
        "اگر سیستم پشتیبانی نکند، از TCP معمولی استفاده می‌شود.",
    "Congestion control": "کنترل ازدحام",
    "System default": "پیش‌فرض سیستم",

    # -- ui/a-shell: UDP noise ----------------------------------------------
    "UDP noise": "نویز UDP",
    "Sends a few random packets before connecting. Hysteria2 servers only.":
        "پیش از اتصال چند بسته‌ی تصادفی می‌فرستد. فقط برای سرورهای Hysteria2.",
    "Packet size": "اندازه‌ی بسته",
    "Delay (ms)": "تأخیر (ms)",

    # -- ui/a-shell: hotspot settings page ----------------------------------
    "Network name": "نام شبکه",
    "New": "جدید",
    "WPA2": "WPA2",
    "WPA3 (if your Wi-Fi card supports it)": "WPA3 (اگر کارت Wi-Fi پشتیبانی کند)",
    "Automatic": "خودکار",
    "2.4 GHz": "2.4 GHz",
    "5 GHz": "5 GHz",
    "Band": "باند",
    "While this computer is on Wi-Fi, the hotspot uses the same band.":
        "وقتی این کامپیوتر به Wi-Fi وصل است، هات‌اسپات از همان باند استفاده می‌کند.",
    "Hide the network name": "پنهان کردن نام شبکه",
    "Keep devices apart": "جدا نگه داشتن دستگاه‌ها",
    "Devices on the hotspot can't reach each other.":
        "دستگاه‌های روی هات‌اسپات به هم دسترسی ندارند.",
    "The network name must be 1 to 32 bytes long.": "نام شبکه باید ۱ تا ۳۲ بایت باشد.",
    "The hotspot password must be 8 to 63 plain characters (A-Z, 0-9, symbols).":
        "رمز هات‌اسپات باید ۸ تا ۶۳ نویسه‌ی ساده باشد (A-Z، 0-9، نمادها).",
    "Changes apply the next time the hotspot starts.":
        "تغییرات از دفعه‌ی بعد که هات‌اسپات روشن شود اعمال می‌شوند.",
    "Keep the name Windows already uses": "همان نامی که ویندوز دارد بماند",
    "Keep the password Windows already uses": "همان رمزی که ویندوز دارد بماند",
    "Windows applies these the next time the hotspot starts, "
    "to its Mobile hotspot as a whole.":
        "ویندوز این‌ها را از دفعه‌ی بعد که هات‌اسپات روشن شود، روی کل "
        "Mobile hotspot خودش اعمال می‌کند.",
    "Sharing the tunnel over a hotspot isn't available on this system.":
        "اشتراک تونل از طریق هات‌اسپات روی این سیستم در دسترس نیست.",

    # -- ui/a-dialogs: REALITY post-quantum verify --------------------------
    "Reality ML-DSA-65 verify": "تأیید ML-DSA-65 در Reality",
    "Invalid ML-DSA-65 key": "کلید ML-DSA-65 نامعتبر است",
    "The ML-DSA-65 verify key must be the server's public key: unpadded base64url, "
    "2603 characters.":
        "کلید تأیید ML-DSA-65 باید کلید عمومی سرور باشد: base64url بدون padding، "
        "۲۶۰۳ کاراکتر.",

    # -- ui/a-dialogs: multi-exit port ---------------------------------------
    "Multi-exit port": "پورت چند خروجی",
    "One local SOCKS port where the username picks the server.":
        "یک پورت SOCKS محلی که نام کاربری، سرور خروجی را انتخاب می‌کند.",
    "Add exit": "افزودن خروجی",
    "Use socks5://USERNAME:PASSWORD@127.0.0.1:PORT. TCP only.":
        "استفاده: socks5://USERNAME:PASSWORD@127.0.0.1:PORT. فقط TCP.",
    "Some exits use a host name. With remote DNS through the tunnel, they can only be "
    "reached while the main server is up.":
        "برخی خروجی‌ها نام دامنه دارند. وقتی DNS از داخل تونل است، فقط زمانی در "
        "دسترس‌اند که سرور اصلی وصل باشد.",
    "username": "نام کاربری",
    "Remove exit": "حذف خروجی",
    "Multi-exit port: {why}": "پورت چند خروجی: {why}",
    "(missing server)": "(سرور حذف شده)",

    # -- ui/a-dialogs: port forwarding page ---------------------------------
    "Port forwarding": "انتقال پورت",
    "Each local port always reaches one fixed address, through the tunnel or directly.":
        "هر پورت محلی همیشه به یک نشانی ثابت می‌رسد، از داخل تونل یا مستقیم.",
    "Add forward": "افزودن انتقال",
    "Newer Xray servers refuse private addresses such as the server's own 127.0.0.1, "
    "so a forward to them will not connect. A shared forward can be used by anyone on "
    "your network.":
        "سرورهای جدیدتر Xray نشانی‌های خصوصی مانند 127.0.0.1 خود سرور را نمی‌پذیرند، "
        "پس انتقال به آن‌ها وصل نمی‌شود. از یک انتقال اشتراکی هر کسی در شبکه‌ی شما "
        "می‌تواند استفاده کند.",
    "host:port": "host:port",
    "Remove forward": "حذف انتقال",
    "Use this forward": "استفاده از این انتقال",
    "LAN": "LAN",
    "Let other devices on your network use this forward.":
        "بگذار دستگاه‌های دیگر شبکه هم از این انتقال استفاده کنند.",
    "Port forwarding: {why}": "انتقال پورت: {why}",
    "Through the tunnel": "از داخل تونل",
    # -- core/chains: validation ---------------------------------------------
    "Hop {hop}: WebSocket (ws) chains can lose responses when a connection closes and are not supported yet.": "گام {hop}: زنجیره‌های WebSocket (ws) ممکن است هنگام بسته شدن اتصال پاسخ را از دست بدهند و هنوز پشتیبانی نمی‌شوند.",
    "The chain has an invalid ID.": "شناسهٔ زنجیره نامعتبر است.",
    "Chain hops must be a list of profile IDs.": "گام‌های زنجیره باید فهرستی از شناسه‌های پروفایل باشند.",
    "A chain must contain between 2 and 8 hops.": "زنجیره باید بین 2 تا 8 گام داشته باشد.",
    "Hop {hop} has an invalid profile ID.": "شناسهٔ پروفایل گام {hop} نامعتبر است.",
    "Profile {uid} is used twice in the chain.": "پروفایل {uid} دو بار در زنجیره استفاده شده است.",
    "The profile for hop {hop} no longer exists: {uid}.": "پروفایل گام {hop} دیگر وجود ندارد: {uid}.",
    "Hop {hop}: protocol {protocol} is not verified for chains.": "گام {hop}: پروتکل {protocol} برای زنجیره‌ها تأیید نشده است.",
    "Hop {hop} is missing an address or credential settings.": "گام {hop} فاقد آدرس یا تنظیمات احراز هویت است.",
    "Hop {hop}: transport {transport} is not verified for chains (including separate XHTTP downloads).": "گام {hop}: انتقال {transport} برای زنجیره‌ها تأیید نشده است (از جمله دانلود جداگانهٔ XHTTP).",
    "Hop {hop}: flow {flow} is not verified for chains.": "گام {hop}: جریان {flow} برای زنجیره‌ها تأیید نشده است.",
    "Mux and XUDP are not verified for chains; disable mux to connect.": "Mux و XUDP برای زنجیره‌ها تأیید نشده‌اند؛ برای اتصال mux را غیرفعال کنید.",
    "The template already uses chain outbound tag {tag}.": "قالب از قبل از برچسب خروجی زنجیرهٔ {tag} استفاده می‌کند.",
    "The template has no proxy outbound for the chain.": "قالب فاقد خروجی proxy برای زنجیره است.",

    # -- Chains: card details -----------------------------------------------
    'ms': 'میلی‌ثانیه',
    'Mbit/s': 'مگابیت/ثانیه',
    'Tested just now': 'همین الان آزمایش شد',
    'Tested {n} min ago': '{n} دقیقه پیش',
    'Tested {n} hours ago': '{n} ساعت پیش',
    'Tested {n} days ago': '{n} روز پیش',
    'Follow the arrows; 42 ms above a link is its added delay.': 'پیکان\u200cها را دنبال کنید؛ ۴۲ میلی\u200cثانیه بالای یک پیوند تأخیر افزودهٔ آن است.',
    '{n} ms': '{n} میلی\u200cثانیه',
    'Entry': 'ورودی',
    'Exit': 'خروجی',
    'Manage this chain; duplicate it to try another exit.': 'مدیریت زنجیره؛ برای امتحان خروجی دیگر از آن کپی بگیرید.',
    'Copy this route; try another exit without losing the original.': 'از مسیر کپی بگیرید؛ خروجی دیگری را بدون از دست دادن مسیر اصلی امتحان کنید.',
    'Hop': 'گام',
    'Server': 'سرور',
    'Transport / security': 'انتقال / امنیت',
    'Outbound tag': 'برچسب خروجی',
    'Dials through': 'اتصال از طریق',
    'Read the route; chain-1 carries the second server.': 'مسیر را بخوانید؛ chain-1 ترافیک سرور دوم را حمل می\u200cکند.',
    "Only the entry is bound to the network card; Xray's dialerProxy dials every later hop through the previous one, never directly through the local network.": 'فقط ورودی به کارت شبکه متصل است؛ dialerProxy در Xray هر گام بعدی را از طریق گام قبلی وصل می\u200cکند و هرگز مستقیماً به شبکهٔ محلی وصل نمی\u200cشود.',
    'Not tested': 'آزمایش نشده',
    'Verified': 'تأیید شده',
    'Skips hops': 'پرش از گام\u200cها',
    'Broken': 'قطع شده',
    'Testing…': 'در حال آزمایش…',
    'Testing link {n} of {total}…': 'آزمایش پیوند {n} از {total}…',
    'A route with a little more reach': 'مسیری برای دسترسی بیشتر',
    'Connect through a relay inside the country, then a server abroad. Test the path to check where your traffic exits.': 'ابتدا به یک واسط داخل کشور و سپس به سروری در خارج وصل شوید. مسیر را آزمایش کنید تا محل خروج ترافیک مشخص شود.',
    '{name} (copy)': '{name} (کپی)',

    # -- Chains: paths and verification -------------------------------------
    'Add the selected server; one more stop on the journey.': 'سرور انتخابی را اضافه کنید؛ یک ایستگاه دیگر در سفر.',
    'Available servers': 'سرورهای موجود',
    'Before a video call, test the path and the country websites see.': 'پیش از تماس تصویری، مسیر و کشوری را که سایت\u200cها می\u200cبینند آزمایش کنید.',
    'Build a path with two to eight servers; give your relay a travel buddy.': 'مسیری با دو تا هشت سرور بسازید؛ برای سرور واسط یک همسفر پیدا کنید.',
    'Cancel test': 'لغو آزمایش',
    'Chains': 'زنجیره\u200cها',
    'Change the route; try a different exit for movie night.': 'مسیر را تغییر دهید؛ برای شب فیلم یک خروجی دیگر امتحان کنید.',
    'Choose a server to add; start with your trusty relay.': 'سروری برای افزودن انتخاب کنید؛ از واسط مطمئن خود شروع کنید.',
    'Choose the route. Verify the exit.': 'مسیر را انتخاب کنید. خروجی را تأیید کنید.',
    'Connect this saved route; your relay has company.': 'به این مسیر ذخیره\u200cشده متصل شوید؛ واسط شما همسفر دارد.',
    'Delete this saved chain?': 'این زنجیرهٔ ذخیره\u200cشده حذف شود؟',
    'Download': 'دریافت',
    'Drag servers to reorder them; the last one is your Internet exit.': 'برای تغییر ترتیب، سرورها را بکشید؛ آخری خروجی اینترنت شماست.',
    'Edit chain': 'ویرایش زنجیره',
    'Exit unverified — test again to confirm the last server': 'خروجی تأیید نشده — برای تأیید سرور آخر دوباره آزمایش کنید',
    'How it is wired': 'اتصال\u200cها چگونه کار می\u200cکنند',
    'Internet': 'اینترنت',
    'Keep this route for later; your next detour is one click away.': 'مسیر را برای بعد نگه دارید؛ گردش بعدی با یک کلیک آغاز می\u200cشود.',
    'Leave without saving; your old route is safe.': 'بدون ذخیره خارج شوید؛ مسیر قبلی محفوظ است.',
    'Missing server': 'سرور حذف\u200cشده',
    'Move down': 'انتقال به پایین',
    'Move this server toward the Internet; choose your final stop.': 'این سرور را به اینترنت نزدیک\u200cتر کنید؛ ایستگاه آخر را انتخاب کنید.',
    'Move this server toward you; make it the first stop.': 'این سرور را به خود نزدیک\u200cتر کنید؛ آن را ایستگاه اول قرار دهید.',
    'Move up': 'انتقال به بالا',
    'Name this route so you can find it later; try Evening detour.': 'برای یافتن آسان مسیر نامی بگذارید؛ مثلاً گردش عصرانه.',
    'New chain': 'زنجیرهٔ جدید',
    'Not tested yet': 'هنوز آزمایش نشده',
    'Ordered path': 'ترتیب مسیر',
    'Peek under the hood: see which outbound carries each hop.': 'نگاهی زیر کاپوت: ببینید هر گام از کدام خروجی عبور می\u200cکند.',
    'Remove': 'حذف',
    'Remove the selected hop; shorten your detour.': 'گام انتخابی را حذف کنید؛ مسیر گردش را کوتاه\u200cتر کنید.',
    'Remove this saved path; your servers stay ready for another adventure.': 'این مسیر ذخیره\u200cشده را حذف کنید؛ سرورها برای سفر بعدی باقی می\u200cمانند.',
    'Round trip': 'رفت\u200cوبرگشت',
    'Stop this test; save the bandwidth for your call.': 'آزمایش را متوقف کنید؛ پهنای باند را برای تماس نگه دارید.',
    'Test cancelled': 'آزمایش لغو شد',
    'This server appears twice.': 'این سرور دو بار آمده است.',
    'Use this path for your traffic; take the scenic route to your next call.': 'ترافیک را از این مسیر بفرستید؛ برای تماس بعدی راهی دیدنی انتخاب کنید.',
    'You': 'شما',
    'breaks here': 'قطع در اینجا',
    'network card': 'کارت شبکه',
    'none': 'بدون',

    'End this connection; time for a pit stop.': 'این اتصال را پایان دهید؛ وقت یک توقف کوتاه است.',

    # -- ui/a-shell: Windows hotspot read ------------------------------------
    "Keep Windows setting": "حفظ تنظیم ویندوز",
    "Couldn't read Windows' hotspot settings. Empty fields keep what Windows already uses.":
        "تنظیمات هات‌اسپات ویندوز خوانده نشد. فیلدهای خالی همان مقدار ویندوز را نگه می‌دارند.",
}
