# Tasks שמורים במסד ו־cron לפי backend

שרת המשחק כבר מחזיק תור `game.Task`; ה־runner שלו הוא `manage.py run_tasks`.
בשרת הטורנירים נוסף תור עצמאי `frontend.Task`, עם runner באותו שם, המשתמש רק במסד
הטורנירים. שרת הניתוח ממשיך עם התור וה־worker הקיימים של `process_analyses`.

## יצירת המשימות וביצוען

- יצירת פקודת מנהל יוצרת Task באותה טרנזקציה. המפתח `admin-command:<UUID>` מונע כפילות.
- ניסיון המסירה המיידי הקיים עובר דרך אותו Task ואותה נעילה. אם הוא נכשל, המשימה
  נשארת בתור. ה־cron מפעיל `run_tasks`, שסורק רק Tasks שהגיע זמנם או שננטשו אחרי קריסה.
- משימת `expire-unstarted-games` בודקת משחקים שלא התחילו ומשחררת יתרות דרך המנגנון
  הקיים. לאחר הצלחה אותה משימה מתוזמנת לדקה הבאה. אין יצירת שורות ניקוי כפולות.
- לכל Task יש `run_at`, מצב, מספר ניסיונות, שגיאה אחרונה ונעילת ביצוע עם אסימון בעלות.
  הנעילה תקפה לשתי דקות ומתחדשת במהלך סריקת המשחקים. תהליך שאיבד בעלות אינו יכול
  לסמן משימה של תהליך אחר כגמורה. פעולות המסירה וההחזרים נשארות אידמפוטנטיות.
- כשל במשימה אינו מדלג על הבאות. ניסיון נוסף מתוזמן בהשהיה של 5 שניות שעולה עד
  חמש דקות; הוא מבוצע בפועל רק בהפעלת cron לאחר המועד. אין הגבלת מספר ניסיונות.
- `run_tasks --limit 50` מבצע לכל היותר 50 Tasks בכל הפעלה. זו אינה פקודת סריקה
  ישירה של פקודות מנהל. אין להפעיל במקביל מתזמן של הפקודות הישנות שעוקף את התור.

מיגרציה `frontend.0008_task` יוצרת את הטבלה, משימת הניקוי ומשימות לכל פקודות המנהל
הישנות שעדיין pending. `manage.py schedule_tasks` מאפשר להשלים יצירה חסרה באופן
אידמפוטנטי. המיגרציה אינה מוסיפה או משנה יתרות.

`backgammon-push.service` נשאר worker קבוע עם ניטור הפעילות שלו. עבודות
`purge_expired`, `reconcile_direct_searches` ו־`reconcile_tranzila` שומרות על התזמון הקיים.
אין שינוי ב־`backgammon-tasks.timer` של שרת המשחק או ב־worker של הניתוח.

## פריסה בשרת הקיים

הנתיבים להלן הם של `/home/dev/backgammon-tournaments-backend`. יש לשמור את משתמש
השירות, קובצי הסביבה והגדרות המסד הקיימים. אל תסיק את המשתמש ממשתמש ה־SSH.
לפני מיגרציה, גבה את מסד הטורנירים שבו השירות משתמש בפועל. במערכת SQLite פעילה
השתמש בגיבוי SQLite עקבי; אין להסתמך על העתקת קובץ בזמן כתיבה או להריץ `--fake`.

```bash
cd /home/dev/backgammon-tournaments-backend
git pull --ff-only
```

הרץ את הבאות באותה סביבה ובאותו משתמש של שירות הטורנירים, אחרי הגיבוי:

```bash
cd /home/dev/backgammon-tournaments-backend/tournaments
../venv/bin/python manage.py migrate --noinput
../venv/bin/python manage.py schedule_tasks
```

יש להריץ מיגרציה לפני הפעלה מחדש של ה־backend המעודכן. הפרויקט טוען `.env` משורש
המאגר, אך אם השירות מגדיר `Environment` או `EnvironmentFile` נוספים, יש לטעון גם אותם
בתהליך המיגרציה. אין לפרסם ערכי סודות בצ'אט או ב־Git.

## הגדרת runner ו־cron

`backgammon-tournaments-tasks.service` הוא רק מעטפת ההרצה היחידה של ה־runner:
הוא שומר על המשתמש והסביבה ומפנה את הלוגים ל־journald. התזמון נעשה ב־cron,
והעבודה עצמה נקבעת לפי שורות Task במסד. אין טיימר חדש ואין שירות נפרד לכל משימה.

```bash
cd /home/dev/backgammon-tournaments-backend
sudo install -m 0644 deploy/tournament-tasks.service.example /etc/systemd/system/backgammon-tournaments-tasks.service
sudoedit /etc/systemd/system/backgammon-tournaments-tasks.service
```

בתבנית יש ערכי דוגמה ל־`User` ול־`EnvironmentFile`. חובה להתאים אותם להגדרות היחידות
הקיימות, כולל `Group`, `Environment` והרשאות מיוחדות אם קיימים. אפשר לבדוק אותן מקומית
עם `sudo systemctl cat backgammon-admin-commands.service backgammon-expire-games.service`;
הפלט עלול לכלול סודות, לכן אין צורך לשלוח אותו. נתיב Python שאומת בשרת הוא
`/home/dev/backgammon-tournaments-backend/venv/bin/python`.

```bash
sudo systemd-analyze verify /etc/systemd/system/backgammon-tournaments-tasks.service
sudo systemctl daemon-reload
```

יש לתקן שגיאות אימות לפני המעבר. ה־cron משתמש ב־`systemctl start` של שירות `oneshot`;
גם כאשר סבב מתארך, systemd אינו מפעיל עותק נוסף של אותה יחידה. ראה
[תיעוד systemd](https://github.com/systemd/systemd/blob/main/man/systemd.service.xml).
נעילת ה־Task מגינה גם במקרה של שני runners שהופעלו בנפרד.

## מעבר מהתזמון הישן

עצור את שני הטיימרים הישנים והמתן לסיום הרצות קיימות בלי להרוג תהליך בזמן החזר
או מסירה. הפעל את ה־runner פעם אחת; אם ההפעלה עצמה נכשלת, הטיימרים הישנים מוחזרים.

```bash
(
  set -euo pipefail
  cd /home/dev/backgammon-tournaments-backend
  sudo systemctl stop backgammon-admin-commands.timer backgammon-expire-games.timer
  for unit in backgammon-admin-commands.service backgammon-expire-games.service; do
    while true; do
      state=$(systemctl show "$unit" -p ActiveState --value)
      case "$state" in
        inactive|failed) break ;;
        *) sleep 1 ;;
      esac
    done
  done
  if ! sudo systemctl start backgammon-tournaments-tasks.service; then
    sudo systemctl start backgammon-admin-commands.timer backgammon-expire-games.timer
    exit 1
  fi
  sudo install -m 0644 deploy/tournament-tasks.cron.example /etc/cron.d/backgammon-tournaments-tasks
  sudo systemctl enable --now cron
  sudo systemctl disable backgammon-admin-commands.timer backgammon-expire-games.timer
  sudo systemctl restart backgammon_tournaments_backend.service
)
```

ה־cron מפעיל את ה־runner מדי דקה. משך הסבב וההשהיה עד דקת cron הבאה עשויים להאריך
את ההמתנה; ניסיון המסירה המיידי של פקודות מנהל נשמר. אין צורך להפעיל מחדש את
ה־cron בכל פריסת קוד. `inactive (dead)` בין סבבים תקין לשירות ה־oneshot.

## בדיקה וחזרה

```bash
systemctl is-active cron
systemctl is-enabled cron
sudo cat /etc/cron.d/backgammon-tournaments-tasks
systemctl show --no-pager backgammon-tournaments-tasks.service -p Result -p ExecMainStatus -p ExecMainStartTimestamp -p ExecMainExitTimestamp
sudo journalctl -u backgammon-tournaments-tasks.service -n 60 --no-pager
systemctl list-timers --all --no-pager --full 'backgammon*'
```

בדוק שזמן ההרצה מתקדם בדקות הבאות ושהטיימרים הישנים אינם פעילים/מופעלים באתחול.
ה־runner רושם מזהה Task ותוצאה. כשל של משימה נשמר ב־`last_error` ומתוזמן מחדש,
ולכן `Result=success` של השירות אינו מעיד שכל המשימות הצליחו. לבדיקת תור בלבד,
הרץ באותה סביבה את הפקודה הבאה; היא אינה מבצעת עבודות או משנה יתרות:

```bash
cd /home/dev/backgammon-tournaments-backend/tournaments
../venv/bin/python manage.py shell -c "from frontend.models import Task; from django.db.models import Count; print(list(Task.objects.values('name', 'status').annotate(count=Count('id'))))"
```

לחזרה לתזמון הישן: הסר מהתיקייה הפעילה רק את קובץ ה־cron החדש, המתן לסיום
הרצת ה־runner ואז הפעל מחדש את שני הטיימרים. השאר את טבלת Tasks; אין צורך
לבטל מיגרציה. אין להשאיר את שני מסלולי התזמון פעילים יחד.

```bash
(
  set -euo pipefail
  sudo mv /etc/cron.d/backgammon-tournaments-tasks /etc/backgammon-tournaments-tasks.cron.disabled
  while true; do
    state=$(systemctl show backgammon-tournaments-tasks.service -p ActiveState --value)
    case "$state" in
      inactive|failed) break ;;
      *) sleep 1 ;;
    esac
  done
  sudo systemctl enable --now backgammon-admin-commands.timer backgammon-expire-games.timer
)
```
