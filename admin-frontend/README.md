# 6B — ממשק הניהול

עודכן: 19.09.2026. Vue 3, TypeScript, Vite 8, Pinia, Tailwind 4 ו־PrimeVue 4. בסיס הנתיבים: /tournaments-admin/.

## הפעלה

נדרש Node ^22.18.0 או >=24.12.0 לפי package.json. מתוך admin-frontend:

~~~sh
pnpm install
pnpm dev --port 5175
~~~

5175 הוא פורט מוצע שנבחר בפקודה. הגדר VITE_API_URL=http://127.0.0.1:8001 אם שרת המועדון המקומי פועל ב־8001. ברירת המחדל בקוד האדמין היא **8002**, בשונה מברירת המחדל של אתר השחקנים. VITE_BACKEND_URL הוא fallback להגדרה. /tournaments-api עובר ל־/api; /tournaments-ws עובר ל־/ws עם תמיכת WebSocket.

## מסכים והרשאות

- /dashboard: תמונת מצב ופעילות.
- /tournaments ו־/tournaments/new: רשימה ויצירה.
- /tournaments/:id/overview, settings, players, live, bracket, standings, results: סביבת טורניר משותפת. draw/attendees/progress הישנים מפנים למסכים החדשים.
- /users, /users/new, /users/:id/edit: משתמשים.
- /direct-play: הגדרות פורמטים ושולחנות.
- /transfers, /transfers/finance, /transfers/payments, /transfers/catalog: תנועות, כספים, תשלומים וקטלוג.

ה־router דורש auth.isAdmin; ההרשאות נאכפות גם בשרת. פעולות כספים רגישות דורשות billing.manage_payments או משתמש־על. מעטפת האדמין מנטרת Push דרך /api/admin/push-health; התראה על worker אינה אישור למסירה לטלפון.

## עיצוב ובדיקות

src/style.css מרכז את מעטפת הניהול הכהה; src/main.ts מגדיר AdminPreset המבוסס על Aura. הטוקנים נפרדים מאתר השחקנים וממשחק React. [מפת העיצוב](../../docs/UI_DESIGN.he.md).

~~~sh
pnpm type-check
pnpm build
pnpm exec vitest run --environment jsdom
~~~

lint/check כוללים פעולות תיקון אוטומטיות. לא הורצו כאן טסטים חדשים. יש לפרוס את dist תחת /tournaments-admin/ ולהפעיל שרת ASGI לנתיבי WebSocket.

[שרת המועדון](../README.md), [תפעול תשלומים](../docs/TRANZILA_OPERATIONS.he.md), [פריסה](../DEPLOY_GAME_AND_CLUB.he.md).
