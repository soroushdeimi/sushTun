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
}
