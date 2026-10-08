import json
from pathlib import Path
from datetime import datetime
import math
import os
import flet as ft

APP_NAME = "انباریار"
APP_DATA_DIR = Path(os.environ.get("FLET_APP_STORAGE_DATA", Path.cwd())).resolve()
APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
DATA_FILE = APP_DATA_DIR / "anbaryar_data.json"
SALES_FILE = APP_DATA_DIR / "anbaryar_sales.json"
UNDO_FILE = APP_DATA_DIR / "anbaryar_last_undo.json"


def parse_money(value):
    if value is None:
        raise ValueError
    text = str(value).strip().replace(",", "").replace("٬", "").replace(" ", "")
    if not text:
        raise ValueError
    return float(text)


def money(value):
    try:
        n = float(value or 0)
        if n.is_integer():
            return f"{int(n):,}"
        return f"{n:,.2f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return str(value)


def round_10000(value):
    return float(math.floor((max(0, float(value)) + 5000) / 10000) * 10000)


def gregorian_to_jalali(gy, gm, gd):
    """Convert Gregorian date to Jalali (Persian) without extra packages."""
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    if gy > 1600:
        jy = 979
        gy -= 1600
    else:
        jy = 0
        gy -= 621
    gy2 = gy + 1 if gm > 2 else gy
    days = (
        365 * gy
        + (gy2 + 3) // 4
        - (gy2 + 99) // 100
        + (gy2 + 399) // 400
        - 80
        + gd
        + g_d_m[gm - 1]
    )
    jy += 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm = 1 + days // 31
        jd = 1 + days % 31
    else:
        jm = 7 + (days - 186) // 30
        jd = 1 + (days - 186) % 30
    return jy, jm, jd


def today_shamsi():
    now = datetime.now()
    jy, jm, jd = gregorian_to_jalali(now.year, now.month, now.day)
    return f"{jy:04d}-{jm:02d}-{jd:02d}"


def current_shamsi_month():
    return today_shamsi()[:7]


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def main(page: ft.Page):
    page.title = APP_NAME
    page.rtl = True
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = "#151515"
    page.padding = 12
    try:
        page.window.width = 1100
        page.window.height = 760
    except Exception:
        pass

    # -------------------- state --------------------
    data = load_json(DATA_FILE, {"products": [], "settings": {"min_stock_default": 5}})
    products = data.get("products", [])
    sales = load_json(SALES_FILE, [])
    last_undo = load_json(UNDO_FILE, None)

    for p in products:
        p.setdefault("name", "")
        p.setdefault("category", "")
        p.setdefault("sale_price", 0)
        p.setdefault("buy_price", 0)
        p.setdefault("stock", 0)
        p.setdefault("shelf", "")
        p.setdefault("last_purchase", "-")
        p.setdefault("last_sale", "-")
        p.setdefault("min_stock", 5)

    # -------------------- helpers --------------------
    def persist():
        save_json(DATA_FILE, {"products": products, "settings": {"min_stock_default": 5}})
        save_json(SALES_FILE, sales)

    def notify(text, color=None):
        page.show_dialog(
            ft.SnackBar(
                content=ft.Text(text, text_align=ft.TextAlign.RIGHT),
                bgcolor=color,
                show_close_icon=True,
            )
        )
        page.update()

    def close_dialog(_=None):
        page.pop_dialog()

    def format_money_field(e):
        field = e.control
        raw = field.value or ""
        digits = "".join(ch for ch in raw if ch.isdigit())
        if not digits:
            return
        formatted = f"{int(digits):,}"
        if field.value != formatted:
            field.value = formatted
            page.update()

    def field(label, value="", password=False):
        return ft.TextField(
            label=label,
            value=str(value),
            text_align=ft.TextAlign.RIGHT,
            password=password,
            border_radius=10,
            filled=True,
            bgcolor="#222222",
        )

    def money_field(label, value="0"):
        f = field(label, money(value))
        f.on_change = format_money_field
        return f

    def selected_names():
        return [cb.data for cb in bulk_checks if cb.value]

    def show_low_stock_dialog():
        low = [p for p in products if int(p.get("stock", 0)) <= int(p.get("min_stock", 5))]
        if not low:
            notify("✅ فعلاً کالای کم‌موجودی نداریم.")
            return
        rows = [
            ft.Text("⚠️ هشدار سیستم انباریار", size=20, weight=ft.FontWeight.BOLD, color=ft.Colors.AMBER_300),
            ft.Divider(),
        ]
        for p in low:
            rows.append(ft.Text(f"• {p['name']} — موجودی: {int(p['stock'])} | حداقل: {int(p['min_stock'])}", text_align=ft.TextAlign.RIGHT))
        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("هشدار سیستم انباریار"),
            content=ft.Column(rows, tight=True, scroll=ft.ScrollMode.AUTO),
            actions=[ft.Button(content="OK", on_click=close_dialog)],
        )
        page.show_dialog(dlg)

    # -------------------- list view --------------------
    search = ft.TextField(label="جستجوی کالا", prefix_icon=ft.Icons.SEARCH, text_align=ft.TextAlign.RIGHT, on_change=lambda e: render_products())
    category_filter = ft.Dropdown(
        label="دسته",
        options=[ft.DropdownOption(key="ALL", text="همه")],
        value="ALL",
        width=220,
    )
    product_list = ft.ListView(expand=True, spacing=8, auto_scroll=False)
    summary_cards = ft.Row(wrap=True, spacing=8, run_spacing=8)

    def refresh_category_options():
        cats = sorted({p.get("category", "") for p in products if p.get("category", "")})
        category_filter.options = [ft.DropdownOption(key="ALL", text="همه")] + [ft.DropdownOption(key=c, text=c) for c in cats]
        if category_filter.value not in {"ALL", *cats}:
            category_filter.value = "ALL"

    def open_details(p):
        content = ft.Column(
            [
                ft.Text(f"نام کالا: {p['name']}", weight=ft.FontWeight.BOLD),
                ft.Text(f"دسته: {p['category']}"),
                ft.Text(f"قیمت فروش: {money(p['sale_price'])} تومان"),
                ft.Text(f"قیمت خرید: {money(p['buy_price'])} تومان"),
                ft.Text(f"موجودی: {p['stock']}"),
                ft.Text(f"قفسه: {p['shelf'] or '-'}"),
                ft.Text(f"آخرین خرید: {p['last_purchase']}"),
                ft.Text(f"آخرین فروش: {p['last_sale']}"),
                ft.Text(f"حداقل موجودی: {p['min_stock']}"),
            ], tight=True, scroll=ft.ScrollMode.AUTO
        )
        page.show_dialog(ft.AlertDialog(modal=True, title=ft.Text("👁️ اطلاعات کالا"), content=content, actions=[ft.Button(content="بستن", on_click=close_dialog)]))

    def delete_product(name):
        nonlocal products
        p = next((x for x in products if x["name"] == name), None)
        if not p:
            return
        def confirm(_):
            products[:] = [x for x in products if x["name"] != name]
            persist(); close_dialog(); render_products(); notify("کالا حذف شد.", "#7f1d1d")
        page.show_dialog(ft.AlertDialog(modal=True, title=ft.Text("حذف کالا"), content=ft.Text(f"کالای «{name}» حذف شود؟"), actions=[ft.TextButton(content="انصراف", on_click=close_dialog), ft.Button(content="حذف", on_click=confirm)]))

    def render_products():
        refresh_category_options()
        term = (search.value or "").strip().lower()
        cat = category_filter.value or "ALL"
        product_list.controls.clear()
        total_units = sum(int(p["stock"]) for p in products)
        inventory_value = sum(float(p["sale_price"]) * int(p["stock"]) for p in products)
        low_count = sum(1 for p in products if int(p["stock"]) <= int(p["min_stock"]))
        summary_cards.controls = [
            stat_card("کالاها", f"{len(products):,}", ft.Icons.INVENTORY_2),
            stat_card("موجودی کل", f"{total_units:,}", ft.Icons.STORAGE),
            stat_card("ارزش انبار", f"{money(inventory_value)}", ft.Icons.ACCOUNT_BALANCE_WALLET),
            stat_card("کم‌موجودی", f"{low_count:,}", ft.Icons.WARNING_AMBER, clickable=show_low_stock_dialog),
        ]
        for p in products:
            if cat != "ALL" and p.get("category") != cat:
                continue
            if term and term not in p.get("name", "").lower():
                continue
            stock = int(p.get("stock", 0))
            min_stock = int(p.get("min_stock", 5))
            stock_color = ft.Colors.RED_300 if stock <= min_stock else ft.Colors.GREEN_300
            card = ft.Container(
                bgcolor="#202020",
                border_radius=12,
                padding=12,
                content=ft.Column([
                    ft.Row([
                        ft.Text(p["name"], size=18, weight=ft.FontWeight.BOLD, expand=True, text_align=ft.TextAlign.RIGHT),
                        ft.Text(f"موجودی: {stock}", color=stock_color, weight=ft.FontWeight.BOLD),
                    ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
                    ft.Text(f"{p.get('category','')}  •  قیمت فروش: {money(p['sale_price'])} تومان  •  قفسه: {p.get('shelf') or '-'}", color=ft.Colors.GREY_400, text_align=ft.TextAlign.RIGHT),
                    ft.Row([
                        ft.Button(content="اطلاعات", icon=ft.Icons.VISIBILITY, on_click=lambda e, pp=p: open_details(pp)),
                        ft.Button(content="ویرایش", icon=ft.Icons.EDIT, on_click=lambda e, pp=p: open_edit_dialog(pp)),
                        ft.Button(content="فروش", icon=ft.Icons.SELL, on_click=lambda e, pp=p: open_sell_dialog(pp)),
                        ft.IconButton(icon=ft.Icons.DELETE_OUTLINE, icon_color=ft.Colors.RED_300, on_click=lambda e, n=p["name"]: delete_product(n)),
                    ], alignment=ft.MainAxisAlignment.END)
                ])
            )
            product_list.controls.append(card)
        page.update()

    def stat_card(title, value, icon, clickable=None):
        c = ft.Container(
            width=240,
            bgcolor="#202020",
            border_radius=12,
            padding=12,
            content=ft.Row([
                ft.Icon(icon, color=ft.Colors.AMBER_300, size=30),
                ft.Column([ft.Text(title, color=ft.Colors.GREY_400), ft.Text(value, size=20, weight=ft.FontWeight.BOLD)], tight=True, horizontal_alignment=ft.CrossAxisAlignment.END)
            ])
        )
        if clickable:
            c.on_click = lambda e: clickable()
        return c

    # -------------------- add/edit --------------------
    def open_add_dialog(_=None):
        name = field("نام کالا")
        cat = field("دسته")
        price = money_field("قیمت فروش")
        buy = money_field("قیمت خرید")
        stock = field("موجودی", "0")
        shelf = field("قفسه")
        last_purchase = field("تاریخ آخرین خرید", today_shamsi())
        minimum = field("حداقل موجودی", "5")

        def save(_):
            try:
                name_v = name.value.strip(); cat_v = cat.value.strip()
                price_v = parse_money(price.value); buy_v = parse_money(buy.value)
                stock_v = int(stock.value or 0); min_v = int(minimum.value or 5)
                if not name_v or not cat_v or min(stock_v, min_v) < 0:
                    raise ValueError
                if any(p["name"] == name_v for p in products):
                    notify("این کالا قبلاً ثبت شده است.", "#7f1d1d")
                    return
                products.append({
                    "name": name_v, "category": cat_v, "sale_price": price_v, "buy_price": buy_v,
                    "stock": stock_v, "shelf": shelf.value.strip(), "last_purchase": last_purchase.value.strip() or "-",
                    "last_sale": "-", "min_stock": min_v,
                })
                persist(); close_dialog(); render_products(); notify("✅ کالا با موفقیت ثبت شد.", "#166534")
                if stock_v <= min_v:
                    show_low_stock_dialog()
            except ValueError:
                notify("مقادیر واردشده درست نیستند.", "#7f1d1d")

        form = ft.Column([name, cat, price, buy, stock, shelf, last_purchase, minimum], scroll=ft.ScrollMode.AUTO, tight=True)
        page.show_dialog(ft.AlertDialog(modal=True, title=ft.Text("➕ افزودن کالای جدید"), content=form, actions=[ft.TextButton(content="انصراف", on_click=close_dialog), ft.Button(content="ثبت کالا", icon=ft.Icons.SAVE, on_click=save)]))

    def open_edit_dialog(p):
        price = money_field("قیمت فروش", p["sale_price"])
        buy = money_field("قیمت خرید", p["buy_price"])
        stock = field("موجودی", p["stock"])
        shelf = field("قفسه", p.get("shelf", ""))
        buy_date = field("تاریخ آخرین خرید", p.get("last_purchase", "-"))
        minimum = field("حداقل موجودی", p.get("min_stock", 5))

        def save(_):
            try:
                p["sale_price"] = parse_money(price.value)
                p["buy_price"] = parse_money(buy.value)
                p["stock"] = int(stock.value or 0)
                p["shelf"] = shelf.value.strip()
                p["last_purchase"] = buy_date.value.strip() or "-"
                p["min_stock"] = int(minimum.value or 5)
                if min(float(p["sale_price"]), float(p["buy_price"]), int(p["stock"]), int(p["min_stock"])) < 0:
                    raise ValueError
                persist(); close_dialog(); render_products(); notify("✅ اطلاعات کالا به‌روزرسانی شد.", "#166534")
            except ValueError:
                notify("قیمت، موجودی و حداقل موجودی باید عددی و صفر یا بیشتر باشند.", "#7f1d1d")

        form = ft.Column([price, buy, stock, shelf, buy_date, minimum], scroll=ft.ScrollMode.AUTO, tight=True)
        page.show_dialog(ft.AlertDialog(modal=True, title=ft.Text(f"✏️ ویرایش {p['name']}"), content=form, actions=[ft.TextButton(content="انصراف", on_click=close_dialog), ft.Button(content="ذخیره", on_click=save)]))

    # -------------------- sale --------------------
    def open_sell_dialog(p):
        qty = field("تعداد فروش", "1")
        info = ft.Text(f"موجودی فعلی: {p['stock']} | قیمت واحد: {money(p['sale_price'])} تومان", color=ft.Colors.GREY_300)

        def sell(_):
            try:
                q = int(qty.value or 0)
                if q <= 0 or q > int(p["stock"]):
                    raise ValueError
                p["stock"] = int(p["stock"]) - q
                date = today_shamsi()
                p["last_sale"] = date
                sales.append({"name": p["name"], "qty": q, "date": date, "sale_price": float(p["sale_price"]), "buy_price": float(p["buy_price"])})
                persist(); close_dialog(); render_products(); notify(f"✅ فروش {q} عدد ثبت شد.", "#166534")
                if int(p["stock"]) <= int(p["min_stock"]):
                    show_low_stock_dialog()
            except ValueError:
                notify("تعداد فروش باید عدد صحیح مثبت و کمتر یا مساوی موجودی باشد.", "#7f1d1d")

        page.show_dialog(ft.AlertDialog(modal=True, title=ft.Text(f"🛒 فروش {p['name']}"), content=ft.Column([info, qty], tight=True), actions=[ft.TextButton(content="انصراف", on_click=close_dialog), ft.Button(content="ثبت فروش", icon=ft.Icons.SELL, on_click=sell)]))

    # -------------------- bulk price + undo --------------------
    bulk_checks = []
    bulk_round = ft.Checkbox(label="رند به نزدیک‌ترین ۱۰٬۰۰۰ تومان", value=True)
    bulk_price_type = ft.Dropdown(label="قیمت", value="sale", width=220, options=[ft.DropdownOption(key="sale", text="قیمت فروش"), ft.DropdownOption(key="buy", text="قیمت خرید"), ft.DropdownOption(key="both", text="هر دو قیمت")])
    bulk_mode = ft.Dropdown(label="روش تغییر", value="percent", width=220, options=[ft.DropdownOption(key="percent", text="درصدی"), ft.DropdownOption(key="fixed", text="مبلغ ثابت")])
    bulk_action = ft.Dropdown(label="عملیات", value="increase", width=220, options=[ft.DropdownOption(key="increase", text="افزایش"), ft.DropdownOption(key="decrease", text="کاهش")])
    bulk_amount = money_field("مقدار تغییر", "5")
    bulk_list = ft.ListView(height=250, spacing=3, auto_scroll=False)

    def open_bulk_dialog(_=None):
        bulk_checks.clear(); bulk_list.controls.clear()
        select_all = ft.Checkbox(label="انتخاب همه", value=False)
        bulk_list.controls.append(select_all)
        for p in products:
            cb = ft.Checkbox(label=p["name"], value=False, data=p["name"])
            bulk_checks.append(cb)
            bulk_list.controls.append(cb)
        def toggle_all(e):
            for cb in bulk_checks: cb.value = e.control.value
            page.update()
        select_all.on_change = toggle_all

        def apply(_):
            nonlocal last_undo
            names = selected_names()
            if not names:
                notify("حداقل یک کالا را انتخاب کن.", "#7f1d1d"); return
            try: amount = parse_money(bulk_amount.value)
            except ValueError:
                notify("مقدار تغییر عددی نیست.", "#7f1d1d"); return
            if amount < 0:
                notify("مقدار تغییر نمی‌تواند منفی باشد.", "#7f1d1d"); return
            snapshot = {"description": f"تغییر {bulk_price_type.value} - {bulk_mode.value} - {bulk_action.value}", "items": []}
            sign = 1 if bulk_action.value == "increase" else -1
            for p in products:
                if p["name"] not in names: continue
                old = {"name": p["name"], "sale_price": p["sale_price"], "buy_price": p["buy_price"]}
                snapshot["items"].append(old)
                def change(base):
                    result = float(base)
                    if bulk_mode.value == "percent":
                        result += sign * result * amount / 100
                    else:
                        result += sign * amount
                    result = max(0, result)
                    if bulk_round.value:
                        result = round_10000(result)
                    return result
                if bulk_price_type.value in ("sale", "both"):
                    p["sale_price"] = change(p["sale_price"])
                if bulk_price_type.value in ("buy", "both"):
                    p["buy_price"] = change(p["buy_price"])
            last_undo = snapshot
            save_json(UNDO_FILE, snapshot)
            persist(); close_dialog(); render_products(); notify("✅ قیمت‌ها با موفقیت تغییر کردند.", "#166534")

        form = ft.Column([
            ft.Text("کالاهای مورد نظر را انتخاب کن", size=16, weight=ft.FontWeight.BOLD),
            bulk_list,
            ft.Row([bulk_price_type, bulk_mode], wrap=True),
            ft.Row([bulk_action, bulk_amount], wrap=True),
            bulk_round,
            ft.Text("مثال: 1,252,134 → 1,250,000", color=ft.Colors.GREY_500),
        ], scroll=ft.ScrollMode.AUTO, tight=True)
        page.show_dialog(ft.AlertDialog(modal=True, title=ft.Text("💰 تغییر گروهی قیمت"), content=form, actions=[ft.TextButton(content="انصراف", on_click=close_dialog), ft.Button(content="اعمال تغییر", icon=ft.Icons.CHECK, on_click=apply)]))

    def undo_bulk(_=None):
        nonlocal last_undo
        if not last_undo or not last_undo.get("items"):
            notify("هنوز تغییر گروهی قیمتی برای بازگردانی وجود ندارد.", "#854d0e"); return
        def do(_):
            for item in last_undo["items"]:
                p = next((x for x in products if x["name"] == item["name"]), None)
                if p:
                    p["sale_price"] = item["sale_price"]
                    p["buy_price"] = item["buy_price"]
            last_undo = None
            save_json(UNDO_FILE, None); persist(); close_dialog(); render_products(); notify("✅ آخرین تغییر قیمت بازگردانده شد.", "#166534")
        page.show_dialog(ft.AlertDialog(modal=True, title=ft.Text("↩️ بازگردانی"), content=ft.Text(f"{last_undo.get('description','آخرین تغییر')}\n\nقیمت {len(last_undo['items'])} کالا به حالت قبل برگردد؟"), actions=[ft.TextButton(content="انصراف", on_click=close_dialog), ft.Button(content="بازگردانی", on_click=do)]))

    # -------------------- report --------------------
    def open_report(_=None):
        month = ft.TextField(label="ماه", hint_text="مثال: 1405-07", value=current_shamsi_month(), text_align=ft.TextAlign.RIGHT)
        body = ft.Column(scroll=ft.ScrollMode.AUTO, tight=True)

        def build_report(target):
            monthly = {}
            for s in sales:
                if not str(s.get("date", "")).startswith(target):
                    continue
                name = s.get("name", "")
                row = monthly.setdefault(name, {"qty": 0, "sales": 0.0, "profit": 0.0})
                qty = int(s.get("qty", 0)); sale_price = float(s.get("sale_price", 0)); buy_price = float(s.get("buy_price", 0))
                row["qty"] += qty
                row["sales"] += qty * sale_price
                row["profit"] += qty * (sale_price - buy_price)
            total_units = sum(x["qty"] for x in monthly.values())
            total_sales = sum(x["sales"] for x in monthly.values())
            total_profit = sum(x["profit"] for x in monthly.values())
            inventory_value = sum(float(p["sale_price"]) * int(p["stock"]) for p in products)
            body.controls.clear()
            body.controls.extend([
                ft.Text(f"📊 گزارش سود و فروش ماه {target}", size=20, weight=ft.FontWeight.BOLD),
                ft.Container(
                    bgcolor="#202020", border_radius=12, padding=12,
                    content=ft.Column([
                        ft.Text(f"مجموع تعداد فروش: {total_units:,} عدد"),
                        ft.Text(f"مجموع پول فروش این ماه: {money(total_sales)} تومان"),
                        ft.Text(f"سود محاسبه‌شده: {money(total_profit)} تومان"),
                        ft.Text(f"ارزش فعلی انبار: {money(inventory_value)} تومان"),
                    ], tight=True)
                ),
                ft.Text("📦 فروش کالاها در این ماه", size=17, weight=ft.FontWeight.BOLD),
            ])
            if not monthly:
                body.controls.append(ft.Text("در این ماه هیچ فروشی ثبت نشده است.", color=ft.Colors.AMBER_300))
                return
            max_qty = max(x["qty"] for x in monthly.values()) or 1
            for name, row in sorted(monthly.items(), key=lambda kv: (-kv[1]["qty"], kv[0].lower())):
                width = 260 * row["qty"] / max_qty
                body.controls.append(ft.Container(
                    bgcolor="#202020", border_radius=10, padding=10,
                    content=ft.Column([
                        ft.Text(f"{name}  ←  {row['qty']:,} عدد", weight=ft.FontWeight.BOLD),
                        ft.Container(width=max(10, width), height=18, bgcolor="#d4a72c", border_radius=9),
                        ft.Text(f"مبلغ فروش: {money(row['sales'])} تومان | سود: {money(row['profit'])} تومان", color=ft.Colors.GREY_400, size=12),
                    ], spacing=5, horizontal_alignment=ft.CrossAxisAlignment.END)
                ))

        build_report(month.value.strip())
        def update(_): build_report(month.value.strip())
        page.show_dialog(ft.AlertDialog(modal=True, title=ft.Text("📊 گزارش مالی"), content=ft.Column([month, ft.Button(content="نمایش گزارش", icon=ft.Icons.REFRESH, on_click=update), body], tight=True, scroll=ft.ScrollMode.AUTO), actions=[ft.Button(content="بستن", on_click=close_dialog)]))

    # -------------------- backup --------------------
    def backup(_=None):
        save_json(DATA_FILE, {"products": products, "settings": {"min_stock_default": 5}})
        save_json(SALES_FILE, sales)
        notify("✅ پشتیبان محلی انباریار به‌روزرسانی شد.", "#166534")

    # -------------------- navigation --------------------
    def nav_button(text, icon, handler):
        return ft.Button(content=text, icon=icon, on_click=handler)

    add_btn = nav_button("افزودن کالا", ft.Icons.ADD_BOX, open_add_dialog)
    sell_btn = nav_button("ثبت فروش", ft.Icons.SELL, lambda e: open_sell_picker())

    def open_sell_picker():
        options = [ft.DropdownOption(key=p["name"], text=p["name"]) for p in products]
        dd = ft.Dropdown(label="کالا", options=options, width=320)
        def cont(_):
            p = next((x for x in products if x["name"] == dd.value), None)
            if p: close_dialog(); open_sell_dialog(p)
            else: notify("یک کالا را انتخاب کن.", "#7f1d1d")
        page.show_dialog(ft.AlertDialog(modal=True, title=ft.Text("🛒 ثبت فروش"), content=dd, actions=[ft.TextButton(content="انصراف", on_click=close_dialog), ft.Button(content="ادامه", on_click=cont)]))

    toolbar = ft.Row([
        nav_button("افزودن کالا", ft.Icons.ADD_BOX, open_add_dialog),
        sell_btn,
        nav_button("گزارش مالی", ft.Icons.BAR_CHART, open_report),
        nav_button("تغییر گروهی قیمت", ft.Icons.SYNC_ALT, open_bulk_dialog),
        nav_button("بازگردانی", ft.Icons.UNDO, undo_bulk),
        nav_button("هشدار موجودی", ft.Icons.WARNING_AMBER, show_low_stock_dialog),
        nav_button("پشتیبان", ft.Icons.BACKUP, backup),
    ], wrap=True, spacing=8, run_spacing=8)

    header = ft.Container(
        bgcolor="#1e1e1e", border_radius=16, padding=14,
        content=ft.Row([
            ft.Column([ft.Text(APP_NAME, size=28, weight=ft.FontWeight.BOLD, color="#d4a72c"), ft.Text("مدیریت هوشمند کالا و فروش", color=ft.Colors.GREY_400)], horizontal_alignment=ft.CrossAxisAlignment.END, expand=True),
            ft.Icon(ft.Icons.INVENTORY_2, size=44, color="#d4a72c"),
        ])
    )

    page.add(
        header,
        toolbar,
        ft.Row([search, category_filter], wrap=True, spacing=8),
        summary_cards,
        ft.Container(expand=True, content=product_list, padding=4),
    )
    category_filter.on_select = lambda e: render_products()
    render_products()


if __name__ == "__main__":
    ft.run(main)
