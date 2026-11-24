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
