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
```

התבנית הותאמה לשרת Bot1 לפי שתי יחידות הטורנירים העובדות:
`User=administrator`, ללא `Group` מפורש,
`EnvironmentFile=/home/dev/backgammon-tournaments-backend/.env`, ו־Python בנתיב
`/home/dev/backgammon-tournaments-backend/venv/bin/python`.

אם התקנת את התבנית הקודמת והשירות נכשל עם `Failed to load environment files`,
משוך את העדכון והעתק שוב את התבנית באמצעות הפקודות לעיל. התבנית הקודמת הצביעה
לקובץ דוגמה שאינו קיים ב־Bot1 והגדירה משתמש אחר. לאחר ההעתקה יש לבצע
`daemon-reload` ו־`reset-failed`, ואז לחזור למעבר מהטיימרים הישנים כמפורט בהמשך.
שינוי זה אינו דורש מיגרציה חוזרת אם `frontend.0008_task` כבר הוחלה בהצלחה.

בשרת אחר יש להתאים את המשתמש והסביבה להגדרות היחידות המקומיות, כולל `Group`,
`Environment` והרשאות מיוחדות אם קיימים, באמצעות
`sudoedit /etc/systemd/system/backgammon-tournaments-tasks.service`.
אין לשלוח תוכן קובצי סביבה או ערכי סודות.

```bash
sudo systemd-analyze verify /etc/systemd/system/backgammon-tournaments-tasks.service
sudo systemctl daemon-reload
sudo systemctl reset-failed backgammon-tournaments-tasks.service
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
  sudo systemctl enable --now cron
  sudo systemctl is-active --quiet cron
  sudo install -m 0644 deploy/tournament-tasks.cron.example /etc/backgammon-tournaments-tasks.cron.pending
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
  if ! sudo mv /etc/backgammon-tournaments-tasks.cron.pending /etc/cron.d/backgammon-tournaments-tasks; then
    sudo systemctl start backgammon-admin-commands.timer backgammon-expire-games.timer
    exit 1
  fi
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

## אירועי מצב משחק במקום שידור אחרי כל פעולה

שרת המשחק שומר בתור Task הקיים רק אירוע התחלה ושינוי הדרישה לטיפול מנהל.
שמירת האירוע נעשית באותה טרנזקציה שבה משתנה החדר; אין פנייה לשרת הטורנירים
מתוך הטרנזקציה או אחרי כל מהלך וחיבור מחדש. מסירת תוצאות נשארת במסלול ה־outbox הקיים.

המשימה `game.link.live.deliver_status_event` מכילה גוף קבוע, `event_id` קבוע
ו־`event_revision` עולה לכל חדר. ניסיון חוזר שולח את אותו הגוף עם nonce חדש.
המקבל מאשר את מזהה האירוע ומתעלם מכפילויות ומאירועים ישנים, גם כשמספר פעולות
המשחק לא השתנה. משימות snapshot ישנות עדיין ניתנות להרצה, אך אינן דורסות אירוע
מצב חדש. כשל זמני מתוזמן שוב בהשהיה גדלה; סירוב קבוע נשמר כ־`blocked` לבדיקה.

מסך המנהל מציג מצב משחק ודרישה מפורשת לטיפול מנהל. שקט של 120 שניות אינו
מסמן משחק כתקוע, ונתוני ניקוד, קובייה ותור שבאירוע אינם מוצגים כנתונים חיים.
זמן תחילת המשחק מגיע מהאירוע; זמן קבלתו אינו מוצג כזמן פעולה אחרונה.

סדר העדכון: קודם שרת הטורנירים ומסך המנהל, שמקבלים גם snapshots ישנים; אחר כך
שרת המשחק וה־worker שלו. בשרת המשחק נוספה המיגרציה
`game.0019_tournamentlink_status_events`. לפני הפעלת הקוד יש לגבות את המסד ולבדוק
את רשימת המיגרציות הממתינות בסביבה ובמשתמש של השירות, ואז להריץ `manage.py migrate`.
אין צורך במיגרציה חדשה בשרת הטורנירים עבור אירועי המצב.
worker המשחק הקיים חייב לפעול; תדירות הפעלתו משפיעה על זמן הגעת האירוע.
חדר שכבר התחיל לפני העדכון אינו מקבל אירוע התחלה בדיעבד.

פקודות הבדיקה להרצה בסביבת Python תקינה של כל שרת, עם הגדרות GameLink תקינות
(כולל כתובת משחק HTTPS בשרת הטורנירים):

```powershell
Set-Location 'C:\Users\User\Desktop\projects\backgammon\Backgammon Game\backend'
python manage.py test game.link.test_status_events game.link.test_live_snapshot_consistency game.link.tests game.tests.integration.test_presence game.tests.gameplay.test_turn_intents

Set-Location 'C:\Users\User\Desktop\projects\backgammon\backgammon-tournaments-backend\tournaments'
python manage.py test gamelink.test_status_events gamelink.tests.LiveSnapshotCallbackViewTest gamelink.tests.DirectPlayLiveSnapshotTest gamelink.test_entry_admission frontend.test_control_room frontend.test_match_administration

Set-Location 'C:\Users\User\Desktop\projects\backgammon\backgammon-tournaments-backend\admin-frontend'
pnpm exec vitest run src/services/tournamentStatusEvents.spec.ts src/pages/TournamentProgressView.spec.ts src/components/TournamentFixtureCard.spec.ts src/components/tournament/TournamentMatchDialog.spec.ts
pnpm run build
```

יש לבדוק גם במובייל שמשחק שקט נשאר פעיל, שהיעדרות שמחייבת מנהל מופיעה באזור
הטיפול, ושמסירת תוצאה מסיימת את המשחק ואינה נדרסת בידי אירוע מצב מאוחר.
הפקודות והמיגרציה שבסעיף זה לא הורצו במהלך השינוי המקומי.

## התאמת נעילות ל־PostgreSQL

מסלולי הכניסה לטורניר והגשת התוצאה נועלים במפורש את רשומת הטורניר ואת
רשומת המשחק. קשרים ליוצר, לשחקנים ולחשבונות שיכולים להיות ריקים נקראים
באמצעות `select_related`, אך אינם נכללים ב־`FOR UPDATE`. גם קליטת תוצאה
במשחק ישיר נועלת תחילה רק את השולחן; נעילת החשבונות לצורך עדכון יתרות
ודירוגים נשארת במסלול הסליקה הקיים. השינוי מונע שגיאת PostgreSQL של נעילת
הצד הריק של `OUTER JOIN` ונעילות נוספות על רשומות שנקראות בלבד.

בשרת המשחק פקודות המנהל ופקודת `cancel_linked_rooms` משתמשות ב־
`game.link.locking.lock_linked_room`: קודם נעילת החדר ורק אחריה נעילת הקישור.
כל נעילה של מצב המשחק באותו מסלול מתבצעת אחרי נעילת החדר. הקישור נבדק שוב
תחת הנעילה, כך שקישור שנמחק או הועבר בזמן ההמתנה אינו משמש לביצוע הפקודה.
ביטול החדרים עדיין דורש `--execute`; אין לבצע את הפקודה לצורך בדיקת המעבר.

השינוי הזה אינו מוסיף מיגרציה. מיגרציות קודמות, כולל אירועי המצב, עדיין
נדרשות במסד היעד. הגדרות החיבור ל־PostgreSQL חייבות להיות זהות עבור ה־API,
ה־WebSocket וה־worker של אותו שרת. מנגנון `BEGIN IMMEDIATE` שייך ל־SQLite
ואינו מופעל כשה־ENGINE הוא `django.db.backends.postgresql`.

בדיקות המקביליות החדשות משתמשות ב־`TransactionTestCase` ובחיבורים נפרדים.
הן מסומנות לדילוג ב־SQLite; הרצה עם דילוג אינה מאמתת את המעבר ל־PostgreSQL.
בדוק תחילה את ה־ENGINE בסביבת השירות, ללא הצגת פרטי החיבור או סודות, ואז הרץ
את הבדיקות במסד הבדיקות של Django:

```powershell
Set-Location 'C:\Users\User\Desktop\projects\backgammon\Backgammon Game\backend'
python manage.py shell -c "from django.conf import settings; print(settings.DATABASES['default']['ENGINE'])"
python manage.py test game.link.test_postgresql_locking game.link.tests.AdminCommandTests game.link.tests.CancelLinkedRoomsCommandTests game.link.test_status_events

Set-Location 'C:\Users\User\Desktop\projects\backgammon\backgammon-tournaments-backend\tournaments'
python manage.py shell -c "from django.conf import settings; print(settings.DATABASES['default']['ENGINE'])"
python manage.py test gamelink.test_postgresql_locking gamelink.test_entry_admission gamelink.test_status_events frontend.tests.ApiTournamentProgressPermissionTests frontend.test_match_administration
```

לא הורצו בדיקות, מיגרציות או פעולות על מסד PostgreSQL במסגרת התאמת הקוד הזאת.
