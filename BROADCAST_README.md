# AI Live Broadcast — Ollama Streamer

## מצב תצוגה (DISPLAY-ONLY)

הממשק **לא** מריץ Ollama ולא שומר קבצים חדשים. קבצי `archive/*.html` מגיעים ממערכת חיצונית.

- **חלון הקוד:** כתיבה **רציפה ברקע** (גם בזמן ארכיון), **2 תווים/שנייה**, קירור 60s, **לא** מתאפס במעבר ללייב. **רענון דף (F5):** ממשיך מאותה נקודה בקובץ (`localStorage` — כמו שגרסת הלייב משכה את כל הבuffer מהשרת).
- **מחזור שידור:** 10 שניות קוד → 40+40 ארכיון (ללא שינוי).
- **סאונד:** בדפדפן (ללא שרת). GitHub Pages: [GITHUB_PAGES.md](GITHUB_PAGES.md). מקומי: `http://localhost:8000/broadcast.html`.
- הגדרות: `charsPerSecond`, `fileCooldownMs`, `liveSegmentMs`, `archiveSegmentMs`.

להפעלת גנרציה מהשרת הזה: `DISPLAY_ONLY = False` ב-`broadcast_server.py`.

## הפעלה מהירה
```
START_BROADCAST.bat
```

## מה זה?
קובץ HTML לשידור חי עם OBS שמציג:
- **פעילות Ollama בזמן אמת**: סטטוס, סטרים, זמן סבב וכמות תווים
- **תצוגת יצירה חיה**: ה-HTML האחרון שהמודל ייצר
- **פופ-אפ יצירות קודמות**: כל 35 שניות

## מבנה חדש (מופרד)

כל רכיבי הערוץ נמצאים עכשיו בספריה:

`continue_models2/ollama_activity_channel`

יצירות המודל (HTML + מטא-דאטה JSON) נשמרות ב:

`continue_models2/ollama_activity_channel/archive/`

קובץ ההפעלה הראשי בשורש:

`continue_models2/START_BROADCAST.bat`

רק מפנה לספריה המופרדת.

## הנחיה קבועה

אין יותר תצוגה של prompt על המסך.
המערכת שולחת בכל סבב את אותה הנחיה קבועה מתוך `broadcast.html`:

"Create a unique and visually breathtaking interactive 3D experience in a single HTML file... Include no external dependencies."

לכן כל פעם מתקבלת יצירה שונה על בסיס אותה הנחיה כללית.

## פרמטרים חשובים

בתוך `broadcast.html` ניתן לשנות ב-`CONFIG`:

```javascript
model: 'glm-4.7-flash-gpu',
fallbackModel: 'glm-4.7-flash:q4_k_M',
cycleIntervalMs: 70000,
previousShowMs: 35000
```

## הגדרת OBS

1. הוסף מקור: **Browser Source**
2. URL: `http://localhost:8000/broadcast.html`
3. Width: 1920 | Height: 1080
