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
