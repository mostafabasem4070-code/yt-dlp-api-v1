/* ==========================================================================
   THEME MANAGER (DARK & LIGHT THEMES)
   YouTube API Hub - Cloud Control Center
   ========================================================================== */

(function () {
    const THEME_STORAGE_KEY = 'ytdlp_hub_theme';

    function getPreferredTheme() {
        const saved = localStorage.getItem(THEME_STORAGE_KEY);
        if (saved === 'light' || saved === 'dark') {
            return saved;
        }
        return 'light'; // ثيم Modernize الافتراضي هو الوضع الفاتح الأنيق
    }

    function applyTheme(theme) {
        document.documentElement.setAttribute('data-theme', theme);
        localStorage.setItem(THEME_STORAGE_KEY, theme);
        updateThemeToggleButton(theme);

        // إشعار نظام الرسوم البيانية لإعادة رسم الألوان المتوافقة
        if (window.onThemeChanged) {
            window.onThemeChanged(theme);
        }
    }

    function toggleTheme() {
        const current = document.documentElement.getAttribute('data-theme') || 'dark';
        const next = current === 'dark' ? 'light' : 'dark';
        applyTheme(next);
    }

    function updateThemeToggleButton(theme) {
        const btn = document.getElementById('btnThemeToggle');
        if (!btn) return;

        if (theme === 'light') {
            btn.setAttribute('title', 'التبديل إلى الوضع الداكن (Dark Mode)');
            btn.innerHTML = `
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path>
                </svg>
            `;
        } else {
            btn.setAttribute('title', 'التبديل إلى الوضع الفاتح (Light Mode)');
            btn.innerHTML = `
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <circle cx="12" cy="12" r="5"></circle>
                    <line x1="12" y1="1" x2="12" y2="3"></line>
                    <line x1="12" y1="21" x2="12" y2="23"></line>
                    <line x1="4.22" y1="4.22" x2="5.64" y2="5.64"></line>
                    <line x1="18.36" y1="18.36" x2="19.78" y2="19.78"></line>
                    <line x1="1" y1="12" x2="3" y2="12"></line>
                    <line x1="21" y1="12" x2="23" y2="12"></line>
                    <line x1="4.22" y1="19.78" x2="5.64" y2="18.36"></line>
                    <line x1="18.36" y1="5.64" x2="19.78" y2="4.22"></line>
                </svg>
            `;
        }
    }

    // تطبيق الثيم الأولي فورياً قبل اكتمال تحميل الصفحة لمنع الوميض
    const initialTheme = getPreferredTheme();
    document.documentElement.setAttribute('data-theme', initialTheme);

    window.toggleTheme = toggleTheme;
    window.getCurrentTheme = () => document.documentElement.getAttribute('data-theme') || 'dark';

    window.addEventListener('DOMContentLoaded', () => {
        updateThemeToggleButton(initialTheme);
        const toggleBtn = document.getElementById('btnThemeToggle');
        if (toggleBtn) {
            toggleBtn.addEventListener('click', toggleTheme);
        }
    });
})();
