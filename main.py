# -*- coding: utf-8 -*-
"""دستیار هوشمند انجمن علمی مهندسی صنایع دانشگاه اردکان - ربات تلگرام"""
import os, io, csv, json, sqlite3, asyncio, logging
from datetime import datetime, timedelta
import jdatetime
from telegram import (Update, InlineKeyboardButton as B, InlineKeyboardMarkup as M,
                      ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove)
from telegram.ext import (Application, CommandHandler, CallbackQueryHandler,
                          MessageHandler, ContextTypes, filters)

logging.basicConfig(level=logging.INFO)
TOKEN = os.environ["BOT_TOKEN"]
ADMINS = {int(x) for x in os.environ.get("ADMIN_IDS", "").split(",") if x.strip()}
PUB_CHAT = int(os.environ.get("PUB_CHAT_ID") or (next(iter(ADMINS), 0)))
CARD = os.environ.get("CARD_INFO", "شماره کارت: ----\nبه نام: ----")
CONTACT = os.environ.get("CONTACT_LINK", "https://t.me/your_support")
ASSOC = "انجمن علمی مهندسی صنایع دانشگاه اردکان"
POINT_VALUE = 5000  # هر امتیاز = ۵۰۰۰ تومان (۱۰ امتیاز = ۵۰٬۰۰۰ تومان)
FA = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
KINDS = {"visit": ("بازدیدهای علمی", "🔬"), "course": ("دوره‌ها", "📚"),
         "event": ("همایش‌ها و وبینارها", "🎤")}
STATUS_FA = {"pending": "در انتظار تأیید", "confirmed": "تأیید شده",
             "cancelled": "لغو شده", "rejected": "رد شده"}

# ---------------------------------------------------------------- DB
# Railway: attach a persistent Volume at /data and set DATABASE_PATH=/data/bot.db.
# Locally, the database defaults to ./bot.db.
DB_PATH = os.environ.get("DATABASE_PATH", "bot.db")
db_parent = os.path.dirname(os.path.abspath(DB_PATH))
os.makedirs(db_parent, exist_ok=True)
db = sqlite3.connect(DB_PATH, check_same_thread=False)
db.row_factory = sqlite3.Row
db.executescript("""
create table if not exists users(user_id integer primary key, first_name text, last_name text,
 student_no text, national_id text, major text, entry_year text, phone text, university text default 'دانشگاه اردکان',
 points integer default 0, rules_ok integer default 0);
create table if not exists programs(id integer primary key autoincrement, kind text, title text,
 descr text, starts_at text, place text, cost integer, capacity integer, deadline text, active integer default 1);
create table if not exists registrations(id integer primary key autoincrement, user_id integer,
 program_id integer, status text, paid integer default 0, points_used integer default 0, receipt text,
 attendance text default 'none', reminded integer default 0, created text);
create table if not exists point_requests(id integer primary key autoincrement, user_id integer,
 points integer, status text default 'new');
create table if not exists feedback(id integer primary key autoincrement, user_id integer,
 program_id integer, ctype text, content text);
create table if not exists polls(id integer primary key autoincrement, question text, options text, active integer default 1);
create table if not exists votes(poll_id integer, user_id integer, opt integer, primary key(poll_id,user_id));
create table if not exists relay(chat_id integer, msg_id integer, user_id integer);
""")
# Migration for existing Railway databases created before national_id was added.
_user_columns = {row[1] for row in db.execute("pragma table_info(users)").fetchall()}
if "national_id" not in _user_columns:
    db.execute("alter table users add column national_id text")
    db.commit()


def q(sql, args=(), one=False):
    cur = db.execute(sql, args); db.commit()
    return cur.fetchone() if one else cur.fetchall()


def ex(sql, args=()):
    cur = db.execute(sql, args); db.commit()
    return cur.lastrowid


def get_user(uid): return q("select * from users where user_id=?", (uid,), one=True)
def P(pid): return q("select * from programs where id=?", (pid,), one=True)
def taken(pid): return q("select count(*) n from registrations where program_id=? and status='confirmed'", (pid,), one=True)["n"]
def add_pts(uid, d): q("update users set points=points+? where user_id=?", (d, uid))
def complete(u): return bool(u) and all(u[k] for k in ("first_name", "last_name", "student_no", "national_id", "major", "entry_year", "phone"))

def valid_national_id(value):
    value = value.translate(FA).strip()
    if len(value) != 10 or not value.isdigit() or len(set(value)) == 1:
        return False
    check = int(value[9])
    total = sum(int(value[i]) * (10 - i) for i in range(9)) % 11
    return check == (total if total < 2 else 11 - total)
def tom(n): return f"{n:,} تومان"
def num(s): return int(s.translate(FA).replace(",", "").strip())
def now_iso(): return datetime.now().isoformat(timespec="seconds")
def dt(s): return datetime.fromisoformat(s)
def fmt(d): return jdatetime.datetime.fromgregorian(datetime=d).strftime("%Y/%m/%d ساعت %H:%M")
def short(s): return jdatetime.datetime.fromgregorian(datetime=dt(s)).strftime("%Y/%m/%d")


def parse_j(s):
    d, t = s.translate(FA).strip().split()
    y, m, dd = map(int, d.split("/")); h, mi = map(int, t.split(":"))
    return jdatetime.datetime(y, m, dd, h, mi).togregorian()


# ---------------------------------------------------------------- texts
RULES = f"""📜 قوانین و راهنمای دستیار هوشمند {ASSOC}

🟦 1 حساب و اطلاعات
برای ثبت‌نام، نام و نام خانوادگی، شماره دانشجویی، کد ملی، رشته، سال ورودی، شماره موبایل و دانشگاه را وارد کنید. اطلاعات را درست وارد کنید؛ در پروفایل قابل ویرایش است. اطلاعات و رسیدها برای مدیریت ثبت‌نام و پیگیری در اختیار انجمن قرار می‌گیرد.

🟦 2 ثبت‌نام و ظرفیت
زمان، محل، هزینه، ظرفیت و مهلت ثبت‌نام در صفحه هر برنامه اعلام می‌شود. در برنامه پولی، ارسال رسید به معنی ثبت‌نام قطعی نیست؛ ظرفیت فقط پس از تأیید انجمن اشغال می‌شود..

🟦 3 لغو ثبت‌نام و بازگشت
ثبت‌نام تأییدشده را پیش از شروع بازدید در بخش «ثبت‌نام‌های من» می‌توانید لغو کنید. تا ۴۸ ساعت پیش از شروع، ۸۰٪ مبلغ پرداختی بازمی‌گردد؛ پس از آن وجه بازگشت ندارد. مبلغ به پایین‌ترین تومان گرد می‌شوند. بازگشت وجه بانکی خودکار نیست و باید با انجمن پیگیری شود. برای ثبت‌نام مجدد پس از لغو با انجمن تماس بگیرید.

🟦 4 اطلاع‌رسانی و ارتباط
یادآوری‌ها و گزارش بازدید از طریق همین ربات ارسال می‌شوند؛ لطفاً اعلان‌های ربات را در پیام‌رسان فعال کنید. می‌توانید برای هر بازدید نظر، عکس، ویدئو یا فایل برای انجمن بفرستید. ارتباط و پیگیری:
{CONTACT}

برای ادامه، پس از مطالعه، دکمه تأیید را بزنید."""

GUIDE = """📖 راهنمای ثبت‌نام
1️⃣ از منوی «ورودی جدید هستم» پروفایل خود را کامل کنید (شماره موبایل باید با دکمه اشتراک‌گذاری ارسال شود).
2️⃣ از بخش بازدیدها، دوره‌ها یا همایش‌ها برنامه را انتخاب و «ثبت‌نام» را بزنید.
3️⃣ برنامه رایگان بلافاصله ثبت می‌شود. برنامه پولی را با امتیاز یا کارت‌به‌کارت (و ارسال رسید) پرداخت کنید.
4️⃣ منتظر تأیید انجمن بمانید؛ نتیجه از طریق ربات اطلاع داده می‌شود.
5️⃣ وضعیت و لغو ثبت‌نام: «ثبت‌نام‌های من»."""

ABOUT = f"ℹ️ دستیار هوشمند {ASSOC}\nثبت‌نام بازدیدهای علمی، دوره‌ها، همایش‌ها و وبینارها، پیگیری برنامه‌ها و اطلاع‌رسانی."
WELCOME = f"سلام، خوش اومدی! 👋\n\n🏛 دستیار هوشمند {ASSOC}\n\nبرنامه‌های انجمن شامل بازدیدهای علمی، دوره‌ها، همایش‌ها و وبینارها را ببین و ثبت‌نام کن.\n\n👇 از منوی زیر شروع کن"
STEPS = [("title", "عنوان برنامه را بفرستید:"), ("descr", "توضیحات برنامه:"),
         ("starts_at", "زمان شروع (شمسی) مثل 1405/09/10 09:00:"), ("place", "مکان برگزاری:"),
         ("cost", "هزینه به تومان (۰ برای رایگان):"), ("capacity", "ظرفیت (۰ = نامحدود):"),
         ("deadline", "مهلت ثبت‌نام (شمسی مثل 1405/09/08 23:59) یا - برای «تا زمان شروع»:")]
EDIT_FIELDS = {
    "title": ("عنوان", "عنوان جدید برنامه را بفرستید:"),
    "descr": ("توضیحات", "توضیحات جدید برنامه را بفرستید:"),
    "starts_at": ("زمان شروع", "زمان شروع جدید را شمسی بفرستید؛ مثل 1405/09/10 09:00:"),
    "place": ("مکان", "مکان جدید برگزاری را بفرستید:"),
    "cost": ("هزینه", "هزینه جدید را به تومان بفرستید (۰ = رایگان):"),
    "capacity": ("ظرفیت", "ظرفیت جدید را بفرستید (۰ = نامحدود):"),
    "deadline": ("مهلت ثبت‌نام", "مهلت جدید را شمسی بفرستید؛ مثل 1405/09/08 23:59 یا - برای تا زمان شروع:"),
}
PROMPTS = {"name": "نام و نام خانوادگی خود را وارد کنید:", "sid": "شماره دانشجویی را وارد کنید:",
           "nid": "کد ملی ۱۰ رقمی خود را وارد کنید (بدون خط تیره):",
           "major": "رشته را وارد کنید:", "year": "سال ورودی را وارد کنید (مثلاً 403):"}
ORDER = ["name", "sid", "nid", "major", "year", "phone"]


# ---------------------------------------------------------------- keyboards
def main_menu():
    return M([
        [B("🔬 بازدیدهای علمی", callback_data="cat:visit")],
        [B("📚 دوره‌ها", callback_data="cat:course")],
        [B("🎤 همایش‌ها و وبینارها", callback_data="cat:event")],
        [B("📝 نظرسنجی‌های من", callback_data="poll")],
        [B("🎓 ورودی جدید هستم", callback_data="newbie")],
        [B("📰 ارتباط با تیم نشریه", callback_data="pub")],
        [B("👤 پروفایل من", callback_data="prof"), B("🎟 ثبت‌نام‌های من", callback_data="my")],
        [B("📜 قوانین و مقررات", callback_data="rules")],
        [B("ℹ️ درباره ربات", callback_data="about"), B("📖 راهنمای ثبت‌نام", callback_data="guide")],
    ])


HOME = [B("🏠 منوی اصلی", callback_data="menu")]


def cat_menu(k):
    return M([[B("📅 برنامه‌های پیش رو", callback_data=f"list:{k}:up")],
              [B("📚 برنامه‌های گذشته و آرشیو", callback_data=f"list:{k}:past")], HOME])


async def show(u, text, kb=None):
    qy = u.callback_query
    if qy:
        try:
            await qy.edit_message_text(text, reply_markup=kb); return
        except Exception:
            await qy.message.reply_text(text, reply_markup=kb)
    else:
        await u.effective_message.reply_text(text, reply_markup=kb)


def ptext(p):
    cap = "نامحدود" if not p["capacity"] else f"{taken(p['id'])} از {p['capacity']} (تأییدشده)"
    cost = "رایگان" if not p["cost"] else tom(p["cost"])
    return (f"{KINDS[p['kind']][1]} {p['title']}\n\n{p['descr']}\n\n🗓 زمان: {fmt(dt(p['starts_at']))}\n"
            f"📍 مکان: {p['place']}\n💰 هزینه: {cost}\n👥 ظرفیت: {cap}\n"
            f"⏳ مهلت ثبت‌نام: {fmt(dt(p['deadline']))}")


async def ask_profile(u, c, step):
    c.user_data["st"] = step
    msg = u.effective_message
    if step == "phone":
        kb = ReplyKeyboardMarkup([[KeyboardButton("📱 اشتراک‌گذاری شمارهٔ من", request_contact=True)]],
                                 resize_keyboard=True, one_time_keyboard=True)
        await msg.reply_text("برای تأیید شماره، دکمهٔ اشتراک‌گذاری شمارهٔ خودتان را بزنید.", reply_markup=kb)
    else:
        await msg.reply_text(PROMPTS[step])


# ---------------------------------------------------------------- commands
async def start(u, c):
    c.user_data["st"] = ""
    uid = u.effective_user.id
    q("insert or ignore into users(user_id) values(?)", (uid,))
    if get_user(uid)["rules_ok"]:
        await u.message.reply_text(WELCOME, reply_markup=main_menu()); return
    await u.message.reply_text(f"سلام! به دستیار هوشمند {ASSOC} خوش آمدید. 🌱\n"
                               "اینجا می‌توانید بازدیدهای علمی، دوره‌ها، همایش‌ها و وبینارهای انجمن را ببینید و در آن‌ها ثبت‌نام کنید.")
    await u.message.reply_text(RULES, reply_markup=M([[B("✅ قوانین را خوانده و می‌پذیرم", callback_data="ok")]]))


async def cancel(u, c):
    c.user_data["st"] = ""
    await u.message.reply_text("لغو شد.", reply_markup=ReplyKeyboardRemove())
    await u.message.reply_text(WELCOME, reply_markup=main_menu())


async def admin_cmd(u, c):
    if u.effective_user.id not in ADMINS: return
    await u.message.reply_text(
        "🛠 پنل مدیریت\n\nدستورها:\n/addpoints <آیدی یا شماره دانشجویی> <امتیاز>\n/broadcast <متن>\n"
        "/pollresults <شماره>\n/closepoll <شماره>",
        reply_markup=M([[B("➕ برنامه جدید", callback_data="adm:new")], [B("📋 مدیریت برنامه‌ها", callback_data="adm:progs")],
                        [B("📊 نظرسنجی جدید", callback_data="adm:poll")]]))


async def addpoints(u, c):
    if u.effective_user.id not in ADMINS: return
    try:
        who, pts = c.args[0], num(c.args[1])
        r = q("select * from users where user_id=? or student_no=?", (int(who) if who.isdigit() else 0, who.translate(FA)), one=True)
        add_pts(r["user_id"], pts)
        await u.message.reply_text(f"✅ {pts:+d} امتیاز برای {r['first_name']} {r['last_name']} ثبت شد.")
        await c.bot.send_message(r["user_id"], f"موجودی امتیاز شما {pts:+d} تغییر کرد.")
    except Exception:
        await u.message.reply_text("فرمت: /addpoints 403123456 10")


async def broadcast(u, c):
    if u.effective_user.id not in ADMINS or not c.args: return
    text = u.message.text.split(None, 1)[1]
    n = 0
    for r in q("select user_id from users where rules_ok=1"):
        try:
            await c.bot.send_message(r["user_id"], "📢 " + text); n += 1
        except Exception: pass
        await asyncio.sleep(0.05)
    await u.message.reply_text(f"ارسال شد برای {n} نفر.")


async def pollresults(u, c):
    if u.effective_user.id not in ADMINS or not c.args: return
    p = q("select * from polls where id=?", (int(c.args[0]),), one=True)
    if not p: return
    opts = json.loads(p["options"]); txt = f"📊 {p['question']}\n"
    for i, o in enumerate(opts):
        n = q("select count(*) n from votes where poll_id=? and opt=?", (p["id"], i), one=True)["n"]
        txt += f"\n• {o}: {n}"
    await u.message.reply_text(txt)


async def closepoll(u, c):
    if u.effective_user.id not in ADMINS or not c.args: return
    q("update polls set active=0 where id=?", (int(c.args[0]),))
    await u.message.reply_text("بسته شد.")


# ---------------------------------------------------------------- registration helpers
async def start_reg(u, c, pid):
    uid = u.effective_user.id; usr = get_user(uid); p = P(pid)
    back = M([[B("🔙 بازگشت", callback_data=f"prog:{pid}")]])
    if not complete(usr):
        return await show(u, "برای ثبت‌نام ابتدا باید پروفایل خود را کامل کنید.", M([[B("🎓 تکمیل پروفایل", callback_data="newbie")]]))
    now = datetime.now()
    if not p["active"] or now > dt(p["deadline"]) or now >= dt(p["starts_at"]):
        return await show(u, "⛔ مهلت ثبت‌نام این برنامه تمام شده است.", back)
    if q("select 1 from registrations where user_id=? and program_id=? and status in ('pending','confirmed')", (uid, pid), one=True):
        return await show(u, "شما قبلاً برای این برنامه ثبت‌نام کرده‌اید. وضعیت را در «ثبت‌نام‌های من» ببینید.", back)
    if p["capacity"] and taken(pid) >= p["capacity"]:
        return await show(u, "⛔ ظرفیت این برنامه تکمیل شده است.", back)
    if p["cost"] == 0:
        ex("insert into registrations(user_id,program_id,status,created) values(?,?,'confirmed',?)", (uid, pid, now_iso()))
        return await show(u, "✅ ثبت‌نام شما انجام شد.", M([[B("🎟 ثبت‌نام‌های من", callback_data="my")], HOME]))
    need = -(-p["cost"] // POINT_VALUE)
    pts = usr["points"]
    rows = []
    txt = f"💰 هزینه: {tom(p['cost'])}\n⭐ موجودی امتیاز شما: {pts} (معادل {tom(max(pts, 0) * POINT_VALUE)})\nروش پرداخت را انتخاب کنید:"
    if pts >= need:
        rows.append([B(f"⭐ پرداخت کامل با امتیاز ({need} امتیاز)", callback_data=f"pay:pts:{pid}")])
    elif pts > 0:
        rows.append([B("⭐+💳 ترکیبی (امتیاز + کارت‌به‌کارت)", callback_data=f"pay:mix:{pid}")])
    rows.append([B("💳 کارت‌به‌کارت", callback_data=f"pay:card:{pid}")])
    rows.append([B("🔙 بازگشت", callback_data=f"prog:{pid}")])
    await show(u, txt, M(rows))


def refund_calc(r, p):
    if r["status"] == "pending": return r["points_used"], 0
    if dt(p["starts_at"]) - datetime.now() >= timedelta(hours=48):
        return r["points_used"] * 8 // 10, r["paid"] * 8 // 10
    return 0, 0


async def notify_admins(c, m, text, kb):
    for a in ADMINS:
        try:
            await c.bot.copy_message(a, m.chat_id, m.message_id, caption=text, reply_markup=kb)
        except Exception as e:
            logging.warning("admin notify failed: %s", e)


async def render_att(u, pid):
    p = P(pid)
    rows = q("select r.id,r.attendance,u.first_name,u.last_name from registrations r join users u on u.user_id=r.user_id "
             "where r.program_id=? and r.status='confirmed'", (pid,))
    kb = []
    mark = {"present": "✅", "absent": "❌", "none": "▫️"}
    for r in rows:
        kb.append([B(f"{mark[r['attendance']]} {r['first_name']} {r['last_name']}", callback_data="noop"),
                   B("حاضر", callback_data=f"at:{r['id']}:p"), B("غایب", callback_data=f"at:{r['id']}:a")])
    kb.append([B("🔙 بازگشت", callback_data=f"ap:{pid}")])
    note = "\n(فقط در بازدید علمی: حضور +۱۰ و غیبت −۵ امتیاز)" if p["kind"] == "visit" else "\n(این نوع برنامه امتیاز حضور/غیاب ندارد)"
    await show(u, f"حضور و غیاب: {p['title']}{note}", M(kb))


# ---------------------------------------------------------------- callbacks
async def on_cb(u, c):
    qy = u.callback_query; await qy.answer()
    d = qy.data.split(":"); a = d[0]; uid = u.effective_user.id
    usr = get_user(uid)
    if a == "noop": return
    if a == "ok":
        q("insert or ignore into users(user_id) values(?)", (uid,))
        q("update users set rules_ok=1 where user_id=?", (uid,))
        await qy.message.reply_text("✅ قوانین تأیید شد.")
        await qy.message.reply_text(WELCOME, reply_markup=main_menu()); return
    if not usr or not usr["rules_ok"]:
        await qy.message.reply_text("برای شروع /start را بزنید."); return
    c.user_data["st"] = ""

    if a == "menu": await show(u, WELCOME, main_menu())
    elif a == "cat":
        k = d[1]; await show(u, f"{KINDS[k][1]} {KINDS[k][0]}:", cat_menu(k))
    elif a == "list":
        k, w = d[1], d[2]; n = now_iso()
        if w == "up":
            rows = q("select * from programs where kind=? and active=1 and starts_at>=? order by starts_at", (k, n)); title = "پیش رو"
        else:
            rows = q("select * from programs where kind=? and starts_at<? order by starts_at desc", (k, n)); title = "گذشته و آرشیو"
        back = [B("🔙 بازگشت", callback_data=f"cat:{k}")]
        if not rows:
            await show(u, f"{KINDS[k][0]} ({title})\n\nفعلاً برنامه‌ای در این بخش وجود ندارد.", M([back, HOME]))
        else:
            kb = [[B(f"{p['title']} | {short(p['starts_at'])}", callback_data=f"prog:{p['id']}")] for p in rows] + [back, HOME]
            await show(u, f"{KINDS[k][0]} ({title})\n\nبرای مشاهدهٔ جزئیات یک برنامه را انتخاب کنید 👇", M(kb))
    elif a == "prog":
        p = P(int(d[1])); kb = []
        if dt(p["starts_at"]) >= datetime.now() and p["active"]:
            kb.append([B("📝 ثبت‌نام", callback_data=f"reg:{p['id']}")])
        elif q("select 1 from registrations where user_id=? and program_id=? and status='confirmed'", (uid, p["id"]), one=True):
            kb.append([B("💬 ارسال نظر، عکس یا فایل", callback_data=f"fb:{p['id']}")])
        kb.append([B("🔙 بازگشت", callback_data=f"cat:{p['kind']}")]); kb.append(HOME)
        await show(u, ptext(p), M(kb))
    elif a == "reg": await start_reg(u, c, int(d[1]))
    elif a == "pay":
        mode, pid = d[1], int(d[2]); p = P(pid); usr = get_user(uid)
        need = -(-p["cost"] // POINT_VALUE)
        if p["capacity"] and taken(pid) >= p["capacity"]:
            return await show(u, "⛔ ظرفیت تکمیل شده است.", M([HOME]))
        if mode == "pts":
            if usr["points"] < need: return await show(u, "موجودی امتیاز کافی نیست.", M([HOME]))
            add_pts(uid, -need)
            ex("insert into registrations(user_id,program_id,status,points_used,created) values(?,?,'confirmed',?,?)", (uid, pid, need, now_iso()))
            return await show(u, "✅ ثبت‌نام با امتیاز انجام و قطعی شد.", M([[B("🎟 ثبت‌نام‌های من", callback_data="my")], HOME]))
        pu = min(max(usr["points"], 0), need - 1) if mode == "mix" else 0
        paid = p["cost"] - pu * POINT_VALUE
        add_pts(uid, -pu)
        rid = ex("insert into registrations(user_id,program_id,status,paid,points_used,created) values(?,?,'pending',?,?,?)",
                 (uid, pid, paid, pu, now_iso()))
        c.user_data["st"] = f"rcpt:{rid}"
        extra = f"\n⭐ {pu} امتیاز تا بررسی رسید نگه داشته می‌شود و در صورت رد رسید آزاد می‌شود." if pu else ""
        await show(u, f"مبلغ قابل پرداخت: {tom(paid)}{extra}\n\n{CARD}\n\nپس از واریز، عکس رسید را همین‌جا بفرستید.\n"
                      "⚠️ ارسال رسید به معنی ثبت‌نام قطعی نیست؛ ظرفیت پس از تأیید انجمن اشغال می‌شود.\n(لغو: /cancel)")
    elif a == "my":
        rows = q("select r.id,r.status,p.title from registrations r join programs p on p.id=r.program_id where r.user_id=? order by r.id desc", (uid,))
        if not rows: return await show(u, "هنوز ثبت‌نامی ندارید.", M([HOME]))
        kb = [[B(f"{r['title']} | {STATUS_FA[r['status']]}", callback_data=f"rv:{r['id']}")] for r in rows] + [HOME]
        await show(u, "🎟 ثبت‌نام‌های من:", M(kb))
    elif a == "rv":
        r = q("select * from registrations where id=? and user_id=?", (int(d[1]), uid), one=True); p = P(r["program_id"])
        txt = f"{ptext(p)}\n\n—\nوضعیت: {STATUS_FA[r['status']]}\nمبلغ پرداختی: {tom(r['paid'])}\nامتیاز مصرفی: {r['points_used']}"
        kb = []
        if r["status"] in ("pending", "confirmed") and datetime.now() < dt(p["starts_at"]):
            kb.append([B("❌ لغو ثبت‌نام", callback_data=f"cx:{r['id']}")])
        await show(u, txt, M(kb + [[B("🔙 بازگشت", callback_data="my")], HOME]))
    elif a == "cx":
        r = q("select * from registrations where id=? and user_id=?", (int(d[1]), uid), one=True); p = P(r["program_id"])
        if r["status"] == "pending" and r["receipt"]:
            return await show(u, "رسید شما در حال بررسی است؛ برای لغو با انجمن تماس بگیرید:\n" + CONTACT, M([HOME]))
        pts, amt = refund_calc(r, p)
        await show(u, f"آیا از لغو مطمئنید؟\nبازگشت امتیاز: {pts}\nبازگشت وجه: {tom(amt)}\n"
                      "(پس از ۴۸ ساعت مانده به شروع، وجه و امتیاز بازگشت ندارد؛ بازگشت وجه بانکی باید با انجمن پیگیری شود.)",
                   M([[B("✅ بله، لغو شود", callback_data=f"cy:{r['id']}")], [B("🔙 خیر", callback_data=f"rv:{r['id']}")]]))
    elif a == "cy":
        r = q("select * from registrations where id=? and user_id=?", (int(d[1]), uid), one=True); p = P(r["program_id"])
        if r["status"] not in ("pending", "confirmed") or datetime.now() >= dt(p["starts_at"]):
            return await show(u, "لغو این ثبت‌نام ممکن نیست.", M([HOME]))
        pts, amt = refund_calc(r, p)
        q("update registrations set status='cancelled' where id=?", (r["id"],)); add_pts(uid, pts)
        if amt:
            for ad in ADMINS:
                await c.bot.send_message(ad, f"💸 درخواست بازگشت وجه\nکاربر: {usr['first_name']} {usr['last_name']} ({usr['student_no']})\nکد ملی: {usr['national_id']}\n"
                                             f"برنامه: {p['title']}\nمبلغ: {tom(amt)}\nموبایل: {usr['phone']}")
        await show(u, f"✅ لغو شد. {pts} امتیاز بازگردانده شد." + (f"\nمبلغ {tom(amt)} را با انجمن پیگیری کنید." if amt else ""), M([HOME]))
    elif a == "prof":
        usr = get_user(uid)
        if not complete(usr):
            return await show(u, "پروفایل شما کامل نیست.", M([[B("🎓 تکمیل پروفایل", callback_data="newbie")], HOME]))
        await show(u, f"👤 پروفایل من\n\nنام: {usr['first_name']} {usr['last_name']}\nشماره دانشجویی: {usr['student_no']}\nکد ملی: {usr['national_id']}\n"
                      f"رشته: {usr['major']}\nسال ورودی: {usr['entry_year']}\nموبایل: {usr['phone']}\nدانشگاه: {usr['university']}\n\n"
                      f"⭐ موجودی امتیاز: {usr['points']} (معادل {tom(usr['points'] * POINT_VALUE)})",
                   M([[B("💳 خرید امتیاز", callback_data="buy")], [B("✏️ ویرایش اطلاعات", callback_data="newbie")], HOME]))
    elif a == "newbie":
        await qy.message.reply_text("برای عضویت ورودی جدید، اطلاعات خود را وارد کنید.")
        await ask_profile(u, c, "name")
    elif a == "buy":
        c.user_data["st"] = "buy"
        await show(u, "چند امتیاز می‌خواهید بخرید؟ (مضرب ۱۰؛ هر ۱۰ امتیاز = ۵۰٬۰۰۰ تومان)\nعدد را بفرستید:")
    elif a == "rules": await show(u, RULES, M([HOME]))
    elif a == "guide": await show(u, GUIDE, M([HOME]))
    elif a == "about": await show(u, ABOUT, M([HOME]))
    elif a == "pub":
        c.user_data["st"] = "pub"
        await show(u, "📰 پیام، عکس یا فایل خود را برای تیم نشریه بفرستید.\n(لغو: /cancel)")
    elif a == "fb":
        c.user_data["st"] = f"fb:{d[1]}"
        await show(u, "💬 نظر، عکس، ویدئو یا فایل خود را دربارهٔ این برنامه بفرستید.\n(پایان: /cancel)")
    elif a == "poll":
        rows = q("select * from polls where active=1 and id not in (select poll_id from votes where user_id=?)", (uid,))
        if not rows: return await show(u, "نظرسنجی فعالی برای شما وجود ندارد.", M([HOME]))
        await show(u, "📝 نظرسنجی‌های فعال:", M([HOME]))
        for p in rows:
            kb = [[B(o, callback_data=f"vote:{p['id']}:{i}")] for i, o in enumerate(json.loads(p["options"]))]
            await qy.message.reply_text(f"📊 {p['question']}", reply_markup=M(kb))
    elif a == "vote":
        q("insert or ignore into votes values(?,?,?)", (int(d[1]), uid, int(d[2])))
        await show(u, "✅ رأی شما ثبت شد. ممنون!", M([HOME]))

    # ---------------- ادمین
    elif uid in ADMINS:
        if a == "adm":
            if d[1] == "new":
                await show(u, "نوع برنامه:", M([[B(f"{v[1]} {v[0]}", callback_data=f"nk:{k}")] for k, v in KINDS.items()]))
            elif d[1] == "progs":
                rows = q("select * from programs order by starts_at desc limit 30")
                await show(u, "📋 برنامه‌ها:", M([[B(f"{'✅' if p['active'] else '⛔'} {p['title']} | {short(p['starts_at'])}", callback_data=f"ap:{p['id']}")] for p in rows] or [HOME]))
            elif d[1] == "poll":
                c.user_data["st"] = "poll_q"; await show(u, "متن سؤال نظرسنجی را بفرستید:")
        elif a == "nk":
            c.user_data["np"] = {"kind": d[1]}; c.user_data["st"] = "np:0"
            await show(u, STEPS[0][1])
        elif a == "ap":
            p = P(int(d[1]))
            n = q("select count(*) n from registrations where program_id=? and status in ('pending','confirmed')", (p["id"],), one=True)["n"]
            await show(u, f"{ptext(p)}\n\nثبت‌نام‌کنندگان فعال: {n}",
                       M([[B("🧾 حضور و غیاب", callback_data=f"att:{p['id']}")], [B("📄 خروجی CSV", callback_data=f"csv:{p['id']}")],
                          [B("📢 پیام به ثبت‌نام‌شدگان", callback_data=f"ntf:{p['id']}")],
                          [B("✏️ ویرایش برنامه", callback_data=f"edmenu:{p['id']}")],
                          [B("🔁 فعال/غیرفعال", callback_data=f"tog:{p['id']}")],
                          [B("🗑 حذف / آرشیو برنامه", callback_data=f"del:{p['id']}")],
                          [B("🔙 بازگشت", callback_data="adm:progs")]]))
        elif a == "edmenu":
            pid = int(d[1]); p = P(pid)
            if not p: return await show(u, "برنامه پیدا نشد.", M([[B("🔙 بازگشت", callback_data="adm:progs")]]))
            rows = [[B(label, callback_data=f"edfield:{pid}:{key}")] for key, (label, prompt) in EDIT_FIELDS.items()]
            rows.append([B("🔙 بازگشت به برنامه", callback_data=f"ap:{pid}")])
            await show(u, f"✏️ ویرایش برنامه: {p['title']}\n\nکدام بخش را می‌خواهید تغییر دهید؟", M(rows))
        elif a == "edfield":
            pid, key = int(d[1]), d[2]
            if key not in EDIT_FIELDS or not P(pid): return await show(u, "درخواست نامعتبر است.", M([HOME]))
            c.user_data["st"] = f"ep:{pid}:{key}"
            await show(u, f"ویرایش {EDIT_FIELDS[key][0]} برنامه شماره {pid}\n{EDIT_FIELDS[key][1]}\n\nبرای انصراف /cancel را بزنید.")
        elif a == "del":
            pid = int(d[1]); p = P(pid)
            if not p: return await show(u, "برنامه پیدا نشد.", M([[B("🔙 بازگشت", callback_data="adm:progs")]]))
            n = q("select count(*) n from registrations where program_id=?", (pid,), one=True)["n"]
            f = q("select count(*) n from feedback where program_id=?", (pid,), one=True)["n"]
            mode = "آرشیو" if n or f else "حذف دائمی"
            detail = "چون برای این برنامه ثبت‌نام یا بازخورد وجود دارد، فقط غیرفعال و آرشیو می‌شود و سوابق حفظ می‌شوند." if n or f else "برای این برنامه سابقه ثبت‌نام یا بازخوردی وجود ندارد؛ برنامه برای همیشه حذف می‌شود."
            await show(u, f"⚠️ {mode} برنامه «{p['title']}»؟\n\n{detail}\n\nمطمئن هستید؟",
                       M([[B("✅ بله، ادامه بده", callback_data=f"delyes:{pid}")], [B("❌ انصراف", callback_data=f"ap:{pid}")]]))
        elif a == "delyes":
            pid = int(d[1]); p = P(pid)
            if not p: return await show(u, "این برنامه قبلاً حذف یا آرشیو شده است.", M([[B("📋 مدیریت برنامه‌ها", callback_data="adm:progs")]]))
            n = q("select count(*) n from registrations where program_id=?", (pid,), one=True)["n"]
            f = q("select count(*) n from feedback where program_id=?", (pid,), one=True)["n"]
            if n or f:
                q("update programs set active=0 where id=?", (pid,))
                msg = "📦 برنامه آرشیو شد؛ سوابق ثبت‌نام و بازخوردها حفظ شدند."
            else:
                q("delete from programs where id=?", (pid,))
                msg = "🗑 برنامه برای همیشه حذف شد."
            c.user_data["st"] = ""
            await show(u, msg, M([[B("📋 مدیریت برنامه‌ها", callback_data="adm:progs")]]))
        elif a == "tog":
            q("update programs set active=1-active where id=?", (int(d[1]),)); await show(u, "وضعیت برنامه تغییر کرد.", M([[B("🔙 بازگشت به برنامه", callback_data=f"ap:{d[1]}")]]))
        elif a == "att": await render_att(u, int(d[1]))
        elif a == "at":
            r = q("select r.*,p.kind from registrations r join programs p on p.id=r.program_id where r.id=?", (int(d[1]),), one=True)
            new = "present" if d[2] == "p" else "absent"
            dl = lambda x: 10 if x == "present" else -5 if x == "absent" else 0
            if r["kind"] == "visit": add_pts(r["user_id"], dl(new) - dl(r["attendance"]))
            q("update registrations set attendance=? where id=?", (new, r["id"]))
            await render_att(u, r["program_id"])
        elif a == "csv":
            pid = int(d[1]); buf = io.StringIO(); w = csv.writer(buf)
            w.writerow(["نام", "نام خانوادگی", "شماره دانشجویی", "کد ملی", "رشته", "سال ورودی", "موبایل", "وضعیت", "مبلغ", "امتیاز مصرفی", "حضور"])
            for r in q("select u.*,r.status,r.paid,r.points_used,r.attendance from registrations r join users u on u.user_id=r.user_id where r.program_id=?", (pid,)):
                w.writerow([r["first_name"], r["last_name"], r["student_no"], r["national_id"], r["major"], r["entry_year"], r["phone"], r["status"], r["paid"], r["points_used"], r["attendance"]])
            f = io.BytesIO(buf.getvalue().encode("utf-8-sig")); f.name = f"program_{pid}.csv"
            await qy.message.reply_document(f)
        elif a == "ntf":
            c.user_data["st"] = f"ntf:{d[1]}"; await show(u, "متن پیام را بفرستید (به ثبت‌نام‌های تأییدشده ارسال می‌شود):")
        elif a in ("ra", "rr"):
            r = q("select * from registrations where id=?", (int(d[1]),), one=True); p = P(r["program_id"])
            if r["status"] != "pending": return await qy.message.reply_text("قبلاً بررسی شده است.")
            if a == "ra":
                if p["capacity"] and taken(p["id"]) >= p["capacity"]: return await qy.message.reply_text("⛔ ظرفیت تکمیل است.")
                q("update registrations set status='confirmed' where id=?", (r["id"],))
                await c.bot.send_message(r["user_id"], f"✅ ثبت‌نام شما در «{p['title']}» تأیید شد.")
            else:
                q("update registrations set status='rejected' where id=?", (r["id"],)); add_pts(r["user_id"], r["points_used"])
                await c.bot.send_message(r["user_id"], f"❌ رسید شما برای «{p['title']}» رد شد؛ امتیاز نگه‌داشته‌شده آزاد شد. با انجمن تماس بگیرید:\n{CONTACT}")
            await qy.message.reply_text("✅ انجام شد.")
            try: await qy.edit_message_reply_markup(reply_markup=None)
            except Exception: pass
        elif a in ("pa", "pr"):
            r = q("select * from point_requests where id=?", (int(d[1]),), one=True)
            if r["status"] != "new": return await qy.message.reply_text("قبلاً بررسی شده است.")
            if a == "pa":
                q("update point_requests set status='ok' where id=?", (r["id"],)); add_pts(r["user_id"], r["points"])
                await c.bot.send_message(r["user_id"], f"✅ {r['points']} امتیاز به موجودی شما اضافه شد.")
            else:
                q("update point_requests set status='no' where id=?", (r["id"],))
                await c.bot.send_message(r["user_id"], "❌ رسید خرید امتیاز تأیید نشد. با انجمن تماس بگیرید.")
            await qy.message.reply_text("✅ انجام شد.")
            try: await qy.edit_message_reply_markup(reply_markup=None)
            except Exception: pass


# ---------------------------------------------------------------- messages
async def on_msg(u, c):
    m = u.message
    if not m: return
    uid = u.effective_user.id; st = c.user_data.get("st", "")
    if m.reply_to_message:
        r = q("select user_id from relay where chat_id=? and msg_id=?", (m.chat_id, m.reply_to_message.message_id), one=True)
        if r and (uid in ADMINS or m.chat_id == PUB_CHAT):
            await c.bot.copy_message(r["user_id"], m.chat_id, m.message_id)
            await m.reply_text("✅ برای کاربر ارسال شد."); return
    if m.chat.type != "private": return
    usr = get_user(uid)
    if not usr or not usr["rules_ok"]:
        await m.reply_text("برای شروع /start را بزنید."); return
    t = (m.text or "").strip()
    fid = m.photo[-1].file_id if m.photo else (m.document.file_id if m.document else None)

    if st in PROMPTS:
        if not t: return
        if st == "name":
            parts = t.split(None, 1)
            if len(parts) < 2: return await m.reply_text("نام و نام خانوادگی را با هم وارد کنید.")
            q("update users set first_name=?,last_name=? where user_id=?", (parts[0], parts[1], uid))
        elif st == "sid":
            if not t.translate(FA).isdigit(): return await m.reply_text("شماره دانشجویی فقط عدد است.")
            q("update users set student_no=? where user_id=?", (t.translate(FA), uid))
        elif st == "nid":
            national_id = t.translate(FA).strip()
            if not valid_national_id(national_id):
                return await m.reply_text("❌ کد ملی معتبر نیست. کد ملی باید ۱۰ رقم و دارای رقم کنترل صحیح باشد؛ دوباره وارد کنید:")
            duplicate = q("select user_id from users where national_id=? and user_id<>?", (national_id, uid), one=True)
            if duplicate:
                return await m.reply_text("❌ این کد ملی قبلاً برای حساب دیگری ثبت شده است. اگر اشتباه است با انجمن تماس بگیرید.")
            q("update users set national_id=? where user_id=?", (national_id, uid))
        elif st == "major": q("update users set major=? where user_id=?", (t, uid))
        elif st == "year":
            if not t.translate(FA).isdigit(): return await m.reply_text("سال ورودی را به‌صورت عدد وارد کنید.")
            q("update users set entry_year=? where user_id=?", (t.translate(FA), uid))
        await ask_profile(u, c, ORDER[ORDER.index(st) + 1])
    elif st == "phone":
        if m.contact and m.contact.user_id == uid:
            q("update users set phone=? where user_id=?", (m.contact.phone_number, uid)); c.user_data["st"] = ""
            await m.reply_text("✅ پروفایل شما ذخیره شد.", reply_markup=ReplyKeyboardRemove())
            await m.reply_text(WELCOME, reply_markup=main_menu())
        else:
            await m.reply_text("لطفاً دکمهٔ اشتراک‌گذاری شمارهٔ خودتان را در گفت‌وگوی خصوصی بزنید؛ شمارهٔ تایپ‌شده یا مخاطب فرد دیگر پذیرفته نیست.")
    elif st == "buy":
        try:
            n = num(t); assert n > 0 and n % 10 == 0
        except Exception:
            return await m.reply_text("عدد باید مضرب ۱۰ باشد.")
        rid = ex("insert into point_requests(user_id,points) values(?,?)", (uid, n))
        c.user_data["st"] = f"prcpt:{rid}"
        await m.reply_text(f"مبلغ: {tom(n * POINT_VALUE)}\n\n{CARD}\n\nپس از واریز، عکس رسید را بفرستید.")
    elif st.startswith("rcpt:"):
        if not fid: return await m.reply_text("لطفاً عکس یا فایل رسید را بفرستید.")
        rid = int(st.split(":")[1]); r = q("select * from registrations where id=?", (rid,), one=True); p = P(r["program_id"])
        q("update registrations set receipt=? where id=?", (fid, rid)); c.user_data["st"] = ""
        await notify_admins(c, m, f"🧾 رسید ثبت‌نام\n{usr['first_name']} {usr['last_name']} ({usr['student_no']})\nکد ملی: {usr['national_id']}\nبرنامه: {p['title']}\n"
                                  f"مبلغ: {tom(r['paid'])} | امتیاز: {r['points_used']}",
                            M([[B("✅ تأیید", callback_data=f"ra:{rid}"), B("❌ رد", callback_data=f"rr:{rid}")]]))
        await m.reply_text("✅ رسید دریافت شد. پس از بررسی انجمن، نتیجه اطلاع داده می‌شود.", reply_markup=M([HOME]))
    elif st.startswith("prcpt:"):
        if not fid: return await m.reply_text("لطفاً عکس یا فایل رسید را بفرستید.")
        rid = int(st.split(":")[1]); r = q("select * from point_requests where id=?", (rid,), one=True); c.user_data["st"] = ""
        await notify_admins(c, m, f"🧾 رسید خرید امتیاز\n{usr['first_name']} {usr['last_name']} ({usr['student_no']})\nکد ملی: {usr['national_id']}\n{r['points']} امتیاز = {tom(r['points'] * POINT_VALUE)}",
                            M([[B("✅ تأیید", callback_data=f"pa:{rid}"), B("❌ رد", callback_data=f"pr:{rid}")]]))
        await m.reply_text("✅ رسید دریافت شد. پس از تأیید مدیر، امتیاز اضافه می‌شود.", reply_markup=M([HOME]))
    elif st == "pub" or st.startswith("fb:"):
        pid = int(st.split(":")[1]) if st.startswith("fb:") else None
        head = f"{'💬 نظر برای «' + P(pid)['title'] + '»' if pid else '📰 پیام به نشریه'}\nاز: {usr['first_name']} {usr['last_name']} | id: {uid}" + \
               (f" | @{u.effective_user.username}" if u.effective_user.username else "") + "\nبرای پاسخ روی همین پیام Reply بزنید."
        h = await c.bot.send_message(PUB_CHAT, head)
        cp = await c.bot.copy_message(PUB_CHAT, m.chat_id, m.message_id, reply_to_message_id=h.message_id)
        ex("insert into relay values(?,?,?)", (PUB_CHAT, h.message_id, uid)); ex("insert into relay values(?,?,?)", (PUB_CHAT, cp.message_id, uid))
        if pid: ex("insert into feedback(user_id,program_id,ctype,content) values(?,?,?,?)", (uid, pid, "text" if t else "file", t or fid or ""))
        else: c.user_data["st"] = ""
        await m.reply_text("✅ ارسال شد." + (" می‌توانید مورد دیگری هم بفرستید." if pid else ""), reply_markup=M([HOME]))
    elif uid in ADMINS and st.startswith("ep:"):
        parts = st.split(":")
        pid, key = int(parts[1]), parts[2]
        if key not in EDIT_FIELDS or not P(pid):
            c.user_data["st"] = ""
            return await m.reply_text("برنامه یا فیلد ویرایش پیدا نشد؛ دوباره از پنل مدیریت اقدام کنید.")
        try:
            if key in ("starts_at", "deadline"):
                value = P(pid)["starts_at"] if key == "deadline" and t == "-" else parse_j(t).isoformat(timespec="seconds")
            elif key in ("cost", "capacity"):
                value = num(t)
                if value < 0: raise ValueError("negative value")
            else:
                if not t: raise ValueError("empty value")
                value = t
            if key == "starts_at":
                old_deadline = P(pid)["deadline"]
                # If the deadline previously matched the start time, keep that relationship.
                if old_deadline == P(pid)["starts_at"]:
                    q("update programs set starts_at=?,deadline=? where id=?", (value, value, pid))
                else:
                    q("update programs set starts_at=? where id=?", (value, pid))
            else:
                q(f"update programs set {key}=? where id=?", (value, pid))
        except Exception:
            return await m.reply_text("❌ مقدار یا قالب واردشده درست نیست؛ دوباره بفرستید.\nبرای تاریخ از قالب شمسی مثل 1405/09/10 09:00 استفاده کنید.")
        c.user_data["st"] = ""
        await m.reply_text(f"✅ {EDIT_FIELDS[key][0]} برنامه به‌روزرسانی شد.",
                           reply_markup=M([[B("✏️ ادامه ویرایش", callback_data=f"edmenu:{pid}")],
                                           [B("📋 صفحه برنامه", callback_data=f"ap:{pid}")]]))
    elif uid in ADMINS and st.startswith("np:"):
        np = c.user_data.setdefault("np", {}); idx = int(st.split(":")[1]); key = STEPS[idx][0]
        try:
            if key == "starts_at": np[key] = parse_j(t).isoformat(timespec="seconds")
            elif key == "deadline": np[key] = np["starts_at"] if t == "-" else parse_j(t).isoformat(timespec="seconds")
            elif key in ("cost", "capacity"): np[key] = num(t)
            else: np[key] = t
        except Exception:
            return await m.reply_text("❌ فرمت نادرست؛ دوباره بفرستید.")
        if idx + 1 < len(STEPS):
            c.user_data["st"] = f"np:{idx + 1}"; await m.reply_text(STEPS[idx + 1][1])
        else:
            c.user_data["st"] = ""
            ex("insert into programs(kind,title,descr,starts_at,place,cost,capacity,deadline) values(?,?,?,?,?,?,?,?)",
               tuple(np[k] for k in ("kind", "title", "descr", "starts_at", "place", "cost", "capacity", "deadline")))
            await m.reply_text("✅ برنامه ثبت شد.")
    elif uid in ADMINS and st == "poll_q":
        c.user_data["pq"] = t; c.user_data["st"] = "poll_o"
        await m.reply_text("گزینه‌ها را بفرستید (هر گزینه در یک خط):")
    elif uid in ADMINS and st == "poll_o":
        opts = [x.strip() for x in t.split("\n") if x.strip()]
        if len(opts) < 2: return await m.reply_text("حداقل دو گزینه لازم است.")
        pid = ex("insert into polls(question,options) values(?,?)", (c.user_data["pq"], json.dumps(opts, ensure_ascii=False)))
        c.user_data["st"] = ""
        await m.reply_text(f"✅ نظرسنجی {pid} ساخته شد. نتایج: /pollresults {pid}")
        for r in q("select user_id from users where rules_ok=1"):
            try: await c.bot.send_message(r["user_id"], "📝 یک نظرسنجی جدید دارید؛ از منو «نظرسنجی‌های من» را بزنید.")
            except Exception: pass
    elif uid in ADMINS and st.startswith("ntf:"):
        pid = int(st.split(":")[1]); c.user_data["st"] = ""; n = 0
        for r in q("select user_id from registrations where program_id=? and status='confirmed'", (pid,)):
            try: await c.bot.send_message(r["user_id"], f"📢 {P(pid)['title']}\n\n{t}"); n += 1
            except Exception: pass
        await m.reply_text(f"ارسال شد برای {n} نفر.")
    else:
        await m.reply_text("از منو استفاده کنید 👇", reply_markup=main_menu())


# ---------------------------------------------------------------- reminders
async def remind(c):
    n = datetime.now()
    rows = q("select r.id,r.user_id,p.title,p.starts_at,p.place from registrations r join programs p on p.id=r.program_id "
             "where r.status='confirmed' and r.reminded=0 and p.starts_at>? and p.starts_at<=?",
             (n.isoformat(timespec="seconds"), (n + timedelta(hours=24)).isoformat(timespec="seconds")))
    for r in rows:
        try:
            await c.bot.send_message(r["user_id"], f"⏰ یادآوری: «{r['title']}» فردا برگزار می‌شود.\n🗓 {fmt(dt(r['starts_at']))}\n📍 {r['place']}")
        except Exception: pass
        q("update registrations set reminded=1 where id=?", (r["id"],))


def main():
    app = Application.builder().token(TOKEN).build()
    for name, fn in [("start", start), ("cancel", cancel), ("admin", admin_cmd), ("addpoints", addpoints),
                     ("broadcast", broadcast), ("pollresults", pollresults), ("closepoll", closepoll)]:
        app.add_handler(CommandHandler(name, fn))
    app.add_handler(CallbackQueryHandler(on_cb))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, on_msg))
    app.job_queue.run_repeating(remind, interval=1800, first=15)
    app.run_polling()


if __name__ == "__main__":
    main()
