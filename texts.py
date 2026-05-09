"""
texts.py
--------
Centralized dictionary for multi-language support.
Terminologies strictly use Islamic contexts (Menzuma, Neshida, Audio).
Languages supported: Amharic ('am'), English ('en'), Arabic ('ar').
"""

TEXTS = {
    "am": {
        "WELCOME": (
            "<tg-emoji emoji-id=\"5769143090103193926\">🌙</tg-emoji> አሰላሙ አለይኩም! ወደ Al-Madih ቦት እንኳን በደህና መጡ። <tg-emoji emoji-id=\"5769143090103193926\">🌙</tg-emoji>\n\n"
            "<tg-emoji emoji-id=\"5337110598926766115\">⭐️</tg-emoji> የሚፈልጉትን መንዙማ ወይም ነሺዳ ርዕስ አሁኑኑ ጽፈው ይላኩ። <tg-emoji emoji-id=\"5384110834068783570\">💬</tg-emoji>"
        ),
        "BTN_SEARCH": "🔍 ፈልግ",
        "BTN_CATALOG": "📂 ማውጫ",
        "BTN_PLAYLIST": "🎧 ፕሌይሊስት",
        "BTN_FAV": "❤️ ተወዳጆች",
        "BTN_OPEN_APP": "🌐 Al-Madih",
        "BTN_ADD_PLAYLIST": "➕ ፕሌይሊስት አስገባ",
        "BTN_FAV_ADD": "❤️ ተወዳጅ",
        "BTN_FAV_REMOVE": "💔 አጥፋ",
        
        "MSG_JOIN_REQ": "⚠️ እባክዎ መጀመሪያ ቻናሉን ይቀላቀሉ!",
        "MSG_JOIN_DESC": "ይህንን መንዙማ ወይም PDF ለማግኘት መጀመሪያ የቦቱን ቻናል ይቀላቀሉ።",
        "BTN_JOIN": "📢 ቻናል ተቀላቀል",
        "BTN_VERIFY": "✅ ተቀላቅያለሁ",
        
        "MSG_NOT_FOUND": "😔 የፈለጉት መንዙማ አልተገኘም። እባክዎ የተለየ ቃል ጽፈው ይሞክሩ።",
        "MSG_SUGGESTIONS": "😔 የፈለጉት መንዙማ በቀጥታ አልተገኘም። ምናልባት ከታች ያሉት ሊሆኑ ይችላሉ?",
        
        "PL_EMPTY": "⚠️ ፕሌይሊስቱ ባዶ ነው! ቢያንስ አንድ መንዙማ ያክሉ።",
        "PL_BUILDER": "🎧 *የፕሌይሊስት ማዘጋጃ* — {count}/10\n\nየመንዙማውን ስም ይፈልጉ እና ➕ ይጫኑ።",
        "PL_ADDED": "➕ ገብቷል ({count}/10)",
        "PL_MAX": "🎵 ከ 10 በላይ መንዙማ መጨመር አይቻልም!",
        "PL_EXISTS": "⚠️ አስቀድሞ ገብቷል!",
        "PL_SAVED": "✅ *ፕሌይሊስቱ ተቀምጧል!*\n\n🔗 *ለወዳጅዎ ያጋሩ:*\n`{link}`",
        
        "FAV_SAVED": "❤️ ተቀምጧል",
        "FAV_REMOVED": "💔 ጠፍቷል",
        
        "LANG_MENU": "🌐 እባክዎ ቋንቋ ይምረጡ / Please select your language / يرجى اختيار لغتك",
        "LANG_UPDATED": "✅ ቋንቋዎ ተቀይሯል!",
    },
    
    "en": {
        "WELCOME": (
            "<tg-emoji emoji-id=\"5769143090103193926\">🌙</tg-emoji> Assalamu Alaikum! Welcome to Al-Madih Bot. <tg-emoji emoji-id=\"5769143090103193926\">🌙</tg-emoji>\n\n"
            "<tg-emoji emoji-id=\"5337110598926766115\">⭐️</tg-emoji> Send the title of the Menzuma or Neshida you want to listen to. <tg-emoji emoji-id=\"5384110834068783570\">💬</tg-emoji>"
        ),
        "BTN_SEARCH": "🔍 Search",
        "BTN_CATALOG": "📂 Catalog",
        "BTN_PLAYLIST": "🎧 Playlist",
        "BTN_FAV": "❤️ Favorites",
        "BTN_OPEN_APP": "🌐 Open Al-Madih",
        "BTN_ADD_PLAYLIST": "➕ Add to Playlist",
        "BTN_FAV_ADD": "❤️ Fav",
        "BTN_FAV_REMOVE": "💔 Remove",
        
        "MSG_JOIN_REQ": "⚠️ Please join our channel first!",
        "MSG_JOIN_DESC": "To access this Menzuma or PDF, please join our official channel.",
        "BTN_JOIN": "📢 Join Channel",
        "BTN_VERIFY": "✅ I've Joined",
        
        "MSG_NOT_FOUND": "😔 The requested Menzuma was not found. Please try different keywords.",
        "MSG_SUGGESTIONS": "😔 Exact match not found. Did you mean one of these?",
        
        "PL_EMPTY": "⚠️ Playlist is empty! Add at least one Menzuma.",
        "PL_BUILDER": "🎧 *Playlist Builder* — {count}/10\n\nSearch for a Menzuma and tap ➕ to add it.",
        "PL_ADDED": "➕ Added ({count}/10)",
        "PL_MAX": "🎵 You cannot add more than 10 tracks!",
        "PL_EXISTS": "⚠️ Already in playlist!",
        "PL_SAVED": "✅ *Playlist Saved!*\n\n🔗 *Share this link:*\n`{link}`",
        
        "FAV_SAVED": "❤️ Saved",
        "FAV_REMOVED": "💔 Removed",
        
        "LANG_MENU": "🌐 Please select your language:",
        "LANG_UPDATED": "✅ Language updated successfully!",
    },
    
    "ar": {
        "WELCOME": (
            "<tg-emoji emoji-id=\"5769143090103193926\">🌙</tg-emoji> وعليكم السلام! أهلاً بك في بوت المديح. <tg-emoji emoji-id=\"5769143090103193926\">🌙</tg-emoji>\n\n"
            "<tg-emoji emoji-id=\"5337110598926766115\">⭐️</tg-emoji> أرسل عنوان المنظومة أو النشيد الذي تريده الآن. <tg-emoji emoji-id=\"5384110834068783570\">💬</tg-emoji>"
        ),
        "BTN_SEARCH": "🔍 بحث",
        "BTN_CATALOG": "📂 الفهرس",
        "BTN_PLAYLIST": "🎧 قائمة التشغيل",
        "BTN_FAV": "❤️ المفضلة",
        "BTN_OPEN_APP": "🌐 فتح المديح",
        "BTN_ADD_PLAYLIST": "➕ أضف للقائمة",
        "BTN_FAV_ADD": "❤️ مفضلة",
        "BTN_FAV_REMOVE": "💔 إزالة",
        
        "MSG_JOIN_REQ": "⚠️ يرجى الانضمام إلى القناة أولاً!",
        "MSG_JOIN_DESC": "للحصول على هذه المنظومة أو الملف، يرجى الانضمام إلى قناتنا.",
        "BTN_JOIN": "📢 انضم للقناة",
        "BTN_VERIFY": "✅ انضممت",
        
        "MSG_NOT_FOUND": "😔 لم يتم العثور على المنظومة. يرجى تجربة كلمات أخرى.",
        "MSG_SUGGESTIONS": "😔 لم يتم العثور على تطابق تام. هل تقصد أحد هذه؟",
        
        "PL_EMPTY": "⚠️ قائمة التشغيل فارغة! أضف منظومة واحدة على الأقل.",
        "PL_BUILDER": "🎧 *إنشاء قائمة تشغيل* — {count}/10\n\nابحث عن منظومة واضغط ➕ لإضافتها.",
        "PL_ADDED": "➕ تمت الإضافة ({count}/10)",
        "PL_MAX": "🎵 لا يمكنك إضافة أكثر من 10 مقاطع!",
        "PL_EXISTS": "⚠️ موجود بالفعل في القائمة!",
        "PL_SAVED": "✅ *تم حفظ القائمة!*\n\n🔗 *شارك هذا الرابط:*\n`{link}`",
        
        "FAV_SAVED": "❤️ تم الحفظ",
        "FAV_REMOVED": "💔 تمت الإزالة",
        
        "LANG_MENU": "🌐 يرجى اختيار لغتك:",
        "LANG_UPDATED": "✅ تم تحديث اللغة بنجاح!",
    }
}

def get_text(lang: str, key: str, **kwargs) -> str:
    """
    Safely fetch the localized text. Defaults to Amharic ('am') if lang/key is missing.
    Supports dynamic string formatting via **kwargs.
    """
    if lang not in TEXTS:
        lang = "am"
    text_template = TEXTS[lang].get(key, TEXTS["am"].get(key, ""))
    
    if kwargs:
        try:
            return text_template.format(**kwargs)
        except Exception:
            return text_template
    return text_template
