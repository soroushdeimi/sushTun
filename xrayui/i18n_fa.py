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
    "Linux/Windows process names": "نام فرایندهای Linux/Windows",
    "Process": "فرایند",
    "Advanced": "پیشرفته",
    "Empty rule": "قانون خالی",
    "This rule would match nothing. Add at least one condition.":
        "این قانون با هیچ‌چیز مطابقت نخواهد داشت. حداقل یک شرط اضافه کنید.",

    # -- server_table.py --------------------------------------------------
    "Name": "نام",
    "Delay": "تأخیر",
    "Transport": "انتقال",
    "Subscription": "اشتراک",
    "Type": "نوع",
    "n/a": "نامشخص",
    "Failed": "ناموفق",
    "QR — {name}": "کد QR — {name}",
    "Copy link": "کپی لینک",

    # -- dns_dialog.py ------------------------------------------------------
    "Preset:": "الگو:",
    "Resolvers (one per line, in order):": "سرورهای DNS (هر خط یک مورد، به ترتیب):",
    "Leave empty to keep the template's servers.": "برای حفظ سرورهای پیش‌فرض قالب، خالی بگذارید.",
    "Use literal IPs — a hostname needs another resolver to look it up first.":
        "از آی‌پی مستقیم استفاده کنید — نام میزبان به یک سرور DNS دیگر برای یافتنش نیاز دارد.",
    "Query strategy:": "راهبرد پرس‌وجو:",
    "Template default": "پیش‌فرض قالب",
    "UseIPv4 avoids AAAA answers this IPv4-only tunnel cannot route.":
        "UseIPv4 از پاسخ‌های AAAA که این تونل فقط-IPv4 نمی‌تواند مسیریابی کند جلوگیری می‌کند.",
    "UseIP or UseIPv6 can make clients prefer an IPv6 path that leaves\n"
    "over your physical adapter instead of the tunnel.":
        "UseIP یا UseIPv6 ممکن است باعث شود کلاینت‌ها مسیر IPv6 را ترجیح دهند که از آداپتور\n"
        "فیزیکی شما خارج می‌شود، نه از تونل.",
    "Static overrides (domain = address):": "بازنویسی‌های ثابت (دامنه = آدرس):",
    "Domestic DNS (for sites that go direct):": "DNS داخلی (برای سایت‌هایی که مستقیم می‌روند):",
    "Used only for domains your active routing sends direct.":
        "فقط برای دامنه‌هایی که مسیریابی فعال شما مستقیم می‌فرستد استفاده می‌شود.",
    "Off": "خاموش",
    "Resolve other sites through the tunnel": "سایر سایت‌ها را از طریق تونل حل کن",
    "Recommended if your ISP blocks or tampers with DNS.":
        "در صورتی که ISP شما DNS را مسدود یا دستکاری می‌کند توصیه می‌شود.",
    "DNS queries for other sites go through the tunnel; "
    "the proxy and any resolver hostname still resolve directly.":
        "پرس‌وجوهای DNS برای سایر سایت‌ها از طریق تونل انجام می‌شود؛ "
        "پروکسی و هر نام میزبان سرور DNS همچنان مستقیم حل می‌شوند.",
    "DNS queries leave over your normal connection, not the tunnel.":
        "پرس‌وجوهای DNS از اتصال عادی شما خارج می‌شوند، نه از تونل.",
    "Parallel query": "پرس‌وجوی موازی",
    "Serve stale": "پاسخ‌گویی با داده کهنه",
    "Raw DNS override (replaces everything above):": "بازنویسی خام DNS (جایگزین همه موارد بالا):",
    "Invalid resolver": "سرور DNS نامعتبر",
    "Invalid domestic resolver": "سرور DNS داخلی نامعتبر",
    "Invalid DNS override": "بازنویسی DNS نامعتبر",
    "Validating…": "در حال بررسی…",
    "Validation failed": "بررسی ناموفق بود",
    "DNS settings invalid": "تنظیمات DNS نامعتبر است",

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
    "DISCONNECTED": "قطع",
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
    "Clone": "شبیه‌سازی",
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
    "Routing invalid": "مسیریابی نامعتبر است",

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
    "Splits the TLS handshake into small pieces so filtering can't read it — "
    "try this if servers connect but sites won't load.":
        "دست‌دهی TLS را به تکه‌های کوچک تقسیم می‌کند تا فیلترینگ نتواند آن را بخواند — "
        "اگر سرورها متصل می‌شوند ولی سایت‌ها باز نمی‌شوند این را امتحان کنید.",
    "Routing…": "مسیریابی…",
    "Which routing rules are active.": "کدام قوانین مسیریابی فعال است.",
    "Choose which resolvers the tunnel uses.": "انتخاب کنید تونل از کدام سرورهای DNS استفاده کند.",
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
    "Not running as administrator — connecting will fail.":
        "به‌عنوان مدیر اجرا نشده — اتصال با خطا مواجه خواهد شد.",
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
    "Hotspot sharing on — applies on next connect.":
        "اشتراک‌گذاری هات‌اسپات روشن شد — در اتصال بعدی اعمال می‌شود.",
    "Still running here. Quit from this icon's menu, or press Ctrl+Q.":
        "همچنان در حال اجراست. از منوی این آیکون خارج شوید یا Ctrl+Q را بزنید.",

    # -- dialogs.py: SettingsDialog language ---------------------------------
    "Language": "زبان",
    "Restart sushTun to apply the new language.": "برای اعمال زبان جدید، sushTun را دوباره اجرا کنید.",

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
    "Copy download link": "کپی لینک دانلود",
}
