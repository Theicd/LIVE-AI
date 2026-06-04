# GitHub Pages — שידור מהדפדפן בלבד

## מבנה

```
archive/                    ← כאן מעלים כל HTML חדש
  index-4.7-VER78.html
  index-4.7-VER78.json      ← אופציונלי (prompt לתצוגה)
  manifest.json             ← נוצר אוטומטית — חובה לעדכן אחרי כל העלאה
broadcast.html
broadcast-channel.js
index.html                  ← מפנה ל-broadcast.html
```

**אין חיבור למודל.** תוכנה חיצונית מייצרת HTML → אתה מעלה ל-`archive/`.

## כל פעם שמוסיפים קבצים

1. העלה `index-4.7-VER*.html` (ו-`.json` אם יש) לתיקייה `archive/`
2. הרץ:
   ```
   UPDATE_MANIFEST.bat
   ```
   או: `python scripts/update_archive_manifest.py`
3. `git add archive/` → `commit` → `push`

ב-push ל-`main`, GitHub Actions מריץ שוב את סקריפט ה-manifest ומפרסם Pages.

## הפעלת GitHub Pages (פעם אחת)

1. Repo ב-GitHub → **Settings** → **Pages**
2. Source: **GitHub Actions**
3. אחרי deploy מוצלח, הכתובת:
   `https://<USER>.github.io/<REPO>/broadcast.html`

## OBS

Browser Source → אותו URL (לא localhost).  
סמן **Control audio via OBS**.

## repo בתת-תיקייה

אם ה-URL כולל `/REPO_NAME/`, הממשק מזהה אוטומטית.  
אם לא — ב-`broadcast.html` הוסף:
```javascript
basePath: '/REPO_NAME/'
```

## עדיין localhost?

`START_BROADCAST.bat` + שרת Python — עדיין עובד לפיתוח; ב-GitHub הכל סטטי.
