# خطة «التجربة الاجتماعية الكاملة» لتارا: المراجعة والفجوات وموجات التنفيذ

- **التاريخ:** 2026-11-03
- **الفرع:** `feat/web-social-platform`
- **المصدر:** المواصفات في [`specs/social-experience-spec.md`](specs/social-experience-spec.md) (ومعها ملاحظات التصميم أعلاها)، والصور المرجعية من 2 إلى 8. الصور محفوظة برّه المستودع، لأن فيها أسماء وصور أشخاص آخرين.
- **مراجع الخطة:** [`04-roadmap.md`](04-roadmap.md) (§0 حالة التنفيذ، وخطط الخطوات، والقرارات D1–D13)، و[`02-tara-audit.md`](02-tara-audit.md)، و[`03-feature-comparison.md`](03-feature-comparison.md)، و[`07-work-log.ar.md`](07-work-log.ar.md).
- **نوع الوثيقة:** تحليل للقراءة بس. ما اتغيّرش أي كود.

## طريقة المراجعة

اتراجع كل بند في المواصفات على الكود نفسه: المسارات (`frontend/web/src/router/index.ts`)، والمكوّنات، والـ endpoints (`urls.py` في كل خدمة)، والـ models، والاختبارات. الدليل المكتوب جنب كل بند هو مسار ملف حقيقي، نسبةً لجذر المستودع.

**معنى الحالات:**

| الحالة | المعنى |
|---|---|
| **موجود ومختبَر** | مبني ومتوصّل بالـ backend، وعليه اختبار (pytest أو vitest أو Playwright) |
| **جزئي** | جزء منه موجود، أو الـ backend موجود من غير واجهة (أو العكس)، أو موجود من غير اختبار |
| **غير موجود** | مفيش له كود. اتأكدنا بالبحث (grep) في كل الخدمات |
| **قيد التنفيذ** | وكلاء تانيين بيبنوه دلوقتي، فمش هنخطط له تاني هنا |

**البنود قيد التنفيذ الآن** (مش داخلة في الموجات تحت):
- الجروبات (1.11 و1.12).
- البحث الموحّد v2 (1.15).
- نقل الـ DLQ لكل خدمة (1.0c).
- لوحة إدارة المستخدمين في الإدارة (8.6).

**اختصارات المسارات:**
- `web/` = `frontend/web/src/`
- `svc/` = `services/`

---

## 1. جدول الحالة

### 1.1 صفحة الزائر والدخول والتسجيل

| البند | الحالة | الدليل | الناقص بالظبط | الخدمة المالكة | الاعتماديات |
|---|---|---|---|---|---|
| الزائر يشوف صفحة دخول وتسجيل، مش الـ feed | جزئي | `web/router/index.ts`: `/` بيفتح `LandingView` (`meta.guest`)، والمسجّل بيتحوّل لـ `/home` | `web/views/LandingView.vue` صفحة تسويقية فيها أزرار «ابدأ» و«عندي حساب» بس، ومفيهاش بطاقة دخول. بطاقة الدخول موجودة في `/login` جوه `web/components/brand/AuthLayout.vue`. المطلوب: بطاقة الدخول على `/` نفسها | frontend | — |
| الشعار والعنوان بكلمة ملوّنة ووصف المنصة | موجود ومختبَر | `LandingView.vue` (`landing.headline` و`headlineAccent`)، واختبار مفاتيح الترجمة في `web/__tests__/app.spec.ts` | مجموعة الرسومات (collage) اللي في الصورة 7 | frontend | — |
| حقل الإيميل أو اسم المستخدم | جزئي | `web/views/LoginView.vue` (حقل `email` بس)، و`svc/identity/identity/serializers.py` | الدخول باسم المستخدم مش مدعوم. الـ handle متخزّن في profile مش في identity | identity + profile | قرار 5.6 |
| إظهار وإخفاء كلمة السر | غير موجود | مفيش `Eye` ولا `EyeOff` في `LoginView.vue` ولا `RegisterView.vue` | زر إظهار وإخفاء بـ `aria-pressed` | frontend | — |
| «تذكرني» | غير موجود | مدة الـ refresh ثابتة: `REFRESH_TOKEN_TTL_SECONDS` = 30 يوم في `svc/identity/config/settings.py` | خيار `remember`: لو مش متعلّم، الكوكي بتبقى session cookie | identity + frontend | — |
| نسيت كلمة السر وإعادة التعيين الآمنة | موجود ومختبَر | `auth/password/forgot/` و`reset/`، و`web/views/ForgotPasswordView.vue` و`ResetPasswordView.vue`، واختبارات `svc/identity/identity/tests/test_session_hardening.py` | — | identity | — |
| زر «إنشاء حساب جديد» | موجود ومختبَر | رابط `/register` في `LoginView.vue`، و`web/e2e/auth.spec.ts` | شكل زر outline زي الصورة 7 | frontend | — |
| حقول التسجيل: الاسم الأول والأخير | غير موجود | `RegisterSerializer` بياخد `display_name` بس | `first_name` و`last_name`، والـ `display_name` يتحسب منهم | identity + profile | — |
| حقول التسجيل: اسم المستخدم والإيميل وكلمة السر | موجود ومختبَر | `RegisterSerializer` (handle اختياري بـ regex، والكلمات المحجوزة مرفوضة)، و`svc/identity/identity/tests/test_auth_api.py` | — | identity | — |
| حقول التسجيل: الموبايل | جزئي | التوثيق بعد التسجيل عن طريق تيليجرام: `me/phone/telegram/`، و`svc/identity/identity/tests/test_telegram.py` | حقل اختياري وقت التسجيل يتوثّق بعدين | identity | — |
| تأكيد كلمة السر | غير موجود | `password2` موجود في نموذج Django admin بس (`svc/identity/identity/admin.py`) | حقل في الواجهة، وفحص على السيرفر | identity + frontend | — |
| تاريخ الميلاد | غير موجود | مفيش `birth` ولا `dob` في أي خدمة | البند 2.12 (بوابة العمر، و`is_minor` في التوكن) | identity | قرار الحد الأدنى للعمر (#5 في الـ roadmap) |
| صورة شخصية اختيارية وقت التسجيل | غير موجود | الرفع محتاج حساب مسجّل (`svc/media`) | خطوة «كمّل ملفك» بعد التوثيق، بدل الرفع جوه النموذج نفسه | frontend + media | — |
| الموافقة على الشروط والخصوصية | غير موجود | `Account` مفيهوش حقل موافقة، ومفيش صفحة شروط ولا صفحة خصوصية في الـ router | `terms_version` و`terms_accepted_at`، وصفحتين `/legal/terms` و`/legal/privacy` | identity + frontend | مراجعة قانونية (#6) |
| التحقق من توفّر اسم المستخدم | غير موجود | `generate_handle` في `svc/profile/profiles/services.py` بيزوّد أرقام في صمت | `GET /profile/handles/available/?h=` بحد للطلبات | profile | 2.2 (سجل handles موحّد) |
| التحقق من الإيميل | موجود ومختبَر | `EmailField` بحروف صغيرة | — | identity | — |
| مؤشر قوة كلمة السر | غير موجود | السيرفر بيفرض 10 حروف على الأقل ومعاها validators Django (`services._validate_password`)، والواجهة مفيهاش مؤشر | مؤشر بنفس قواعد السيرفر | frontend | — |
| منع الحسابات المكررة | موجود ومختبَر | `Account.email` فريد ويرجّع 409، والموبايل الموثّق فريد (`account_verified_phone_uniq`)، و`test_register_duplicate_email_conflicts` | ملاحظة مفتوحة: الـ 409 بيكشف إن الإيميل مستخدم (§0 في الـ roadmap) | identity | — |
| توثيق الإيميل وتفعيل الحساب | موجود ومختبَر | `auth/verify-email/` و`resend/`، والحالة PENDING ثم ACTIVE، و`web/e2e/auth.spec.ts` («register, verify through the mailed link, log in») | — | identity | SMTP حقيقي في الإنتاج |
| معالجة أخطاء الدخول | موجود ومختبَر | `web/lib/errors.ts`، و`web/e2e/auth.spec.ts` («a wrong password…»)، و`test_login_throttle.py` | — | identity + frontend | — |
| إدارة الجلسات | موجود ومختبَر | `auth/sessions/`، وتدوير الـ refresh مع كشف إعادة استخدامه، و`web/e2e/auth.spec.ts` (تابين وتسجيل خروج) | — | identity | — |
| الدخول بحسابات التواصل | جزئي | جوجل شغال (`svc/identity/identity/google.py`، و`tests/test_google.py`) | `SocialIdentity.Provider` فيه GOOGLE بس. تجهيز مزوّدين تانيين (Apple وMicrosoft) يبقى بتوسيع الـ enum والتجريد | identity | قرار المزوّدين |
| التحويل لـ `/home` وحماية المسارات (واجهة وسيرفر) | موجود ومختبَر | `router.beforeEach` في `web/router/index.ts`، وكل الـ APIs محتاجة توكن، و`web/e2e/auth.spec.ts` («the redirect param can't leave the site») | — | frontend + كل الخدمات | — |

### 1.2 التنقّل العام (الشريط العلوي، والشريط الجانبي، والموبايل)

| البند | الحالة | الدليل | الناقص بالظبط | الخدمة المالكة | الاعتماديات |
|---|---|---|---|---|---|
| الشريط العلوي: الشعار والبحث العام | موجود ومختبَر | `web/components/layout/AppNavbar.vue` (اقتراحات فورية من `/search/autocomplete/`) | — | frontend + search | — |
| أيقونات في نص الشريط بخط تحت الأيقونة النشطة | جزئي | `navIcons` في `AppNavbar.vue` فيها الرئيسية والأصدقاء والسوق بس، وظاهرة بين `md` و`lg` بس (`hidden md:flex lg:hidden`) | تظهر على الكمبيوتر كمان، ومعاها الجروبات والفعاليات. الفيديو بعد الخطوة 5، والألعاب حسب القرار 5.5 | frontend | الجروبات (قيد التنفيذ)، الخطوة 5 |
| الرسائل والإشعارات بعدّاد | موجود ومختبَر | `MessagesPanel` و`NotificationPanel` في `AppNavbar.vue`، و`web/__tests__/notifications.spec.ts` و`messenger.spec.ts` | — | frontend + notification + chat | — |
| شبكة التطبيقات (القائمة الرئيسية) | جزئي | `web/components/layout/AppsMenu.vue`: شبكة 3 أعمدة فيها 13 رابط | مفيش تصنيفات (التفاصيل في 1.3) | frontend | — |
| الصورة الشخصية بسهم وقائمة | جزئي | `web/components/layout/ProfileMenu.vue`: الإعدادات واللغة والمظهر والخروج | بطاقة «ملفك» فوق، والمساعدة والدعم، والعرض وإمكانية الوصول | frontend | — |
| الشريط الجانبي: 18 بند | جزئي | `web/components/layout/navItems.ts` فيها 10 بنود، ومعاها الإعلانات والإدارة في `LeftSidebar.vue` | ناقص: الذكريات، والجروبات، والريلز، والفيديو، والبث المباشر، والألعاب، والاستوديو، والاحترافي، ومركز الأعمال، والمساعدة. البنود اللي مش مبنية **تستخبى** ومتظهرش معطّلة | frontend | كل وحدة لما تتبني |
| «عرض المزيد» و«عرض أقل» | غير موجود | `LeftSidebar.vue` | طي القائمة بعد 8 بنود | frontend | — |
| تخصيص التنقّل | غير موجود | — | تثبيت البنود وترتيبها، ويتخزّن في profile (`NavPreference`) | profile + frontend | قرار 5.12 |
| «اختصاراتك» وروابط التذييل | غير موجود | التذييل في `LeftSidebar.vue` فيه الاسم والسنة بس | اختصارات للصفحات اللي بتديرها والجروبات، وروابط الخصوصية والشروط والمساعدة | frontend + profile | صفحات الشروط |
| تنقّل الموبايل: الرئيسية، الأصدقاء، إنشاء، فيديو/ريلز، الإشعارات، القائمة | جزئي | `web/components/layout/MobileBottomNavigation.vue`: الرئيسية، الأصدقاء، إنشاء، الرسائل، الإشعارات | تبويب «القائمة» (صفحة `/menu` مخصّصة للموبايل بدل الدرج اللي بيعيد `LeftSidebar`). تبويب الريلز بعد الخطوة 5 | frontend | الخطوة 5 للريلز |
| زر «رسالة جديدة» عائم (الصور 2 إلى 5) | غير موجود | — | زر عائم في آخر الشاشة بيفتح محادثة جديدة | frontend | — |

### 1.3 القائمة الرئيسية المصنّفة

| البند | الحالة | الدليل | الناقص بالظبط | الخدمة المالكة | الاعتماديات |
|---|---|---|---|---|---|
| حسابك: الملف، الأصدقاء، المحفوظات | موجود ومختبَر | المسارات `/u/:handle` و`/friends` و`/saved`، و`web/e2e/profile.spec.ts` و`lists.spec.ts` | — | frontend | — |
| حسابك: الذكريات | غير موجود | مفيش `memories` ولا `on_this_day` في أي خدمة | قرار 5.4، وبعده endpoint في post | post | قرار |
| حسابك: سجل النشاط | غير موجود | `SecurityEvent` في identity ملوش endpoint | البند 2.8 | profile (consumer) | 2.8 |
| اجتماعي: الرئيسية والفعاليات | موجود ومختبَر | `/home` و`/events`، و`svc/post/gatherings/tests/test_gatherings.py`، و`web/e2e/events.spec.ts` | — | post + feed | — |
| اجتماعي: القصص | غير موجود | مفيش app اسمه stories (`svc/post/`) | 1.9 و1.10 | post | 1.9 |
| اجتماعي: الريلز والفيديو | غير موجود | `_video_not_supported` في `svc/post/posts/services.py` بيرجّع 400 | الخطوة 5 (D1) | post + media | الخطوة 5 |
| اجتماعي: الجروبات | قيد التنفيذ | 1.11 و1.12 | — | profile + post | — |
| اجتماعي: البث المباشر | غير موجود | LiveKit مستخدَم للمكالمات بس (`svc/chat/calls/`) | بنية بث (البند 3) | — | بنية تحتية |
| تجاري: السوق وإعلاناتي | موجود ومختبَر | `web/views/MarketplaceView.vue` (تبويب `mine`)، و`my-listings/`، و`svc/marketplace/marketplace/tests/` | — | marketplace | — |
| تجاري: مدير الإعلانات | جزئي | `/ads` و`/ads/campaigns/:id`، و`svc/ads/ads/tests/test_ads.py` | التمويل (6.3)، والترويج لمنشور (sponsored post)، والـ targeting مش مفعّل | ads | الدفع (البند 3) |
| تجاري: مركز الأعمال | غير موجود | — | يتبني كـ «مدير الصفحات» في الموجة 4، وبعدين أداة التخطيط في الموجة 5 | profile + post | 2.7 |
| صانع المحتوى: الاستوديو، مكتبة المحتوى، التحليلات، جاهزية الربح | غير موجود | مفيش `insights` ولا `analytics` في أي خدمة | التفاصيل في 1.7 | post + feed | الموجة 4 |
| احترافي: الملف الاحترافي | جزئي | العمل والتعليم: `profile/me/work/` و`/education/`، و`web/components/profile/ProfileDetails.vue` | الـ headline و«متاح للعمل» (2.4) | profile | 2.4 |
| احترافي: الشركات، الوظائف، الطلبات | غير موجود | — | الخطوة 7 | profile (`careers`) | الخطوة 7 |
| التواصل: الماسنجر والمؤرشف | موجود ومختبَر | `/messages`، و`folder` inbox/archived في `web/views/MessagesView.vue`، و`svc/chat/chat/tests/test_inbox.py` | — | chat | — |
| التواصل: طلبات الرسائل | غير موجود | مفيش model ولا حقل للطلبات أو السبام في `svc/chat/chat/models.py` | 3.6 | chat | — |
| الإدارة: صفحاتي وإدارة الصفحات | جزئي | `web/views/PagesView.vue` و`PageDetailView.vue` | مدير صفحات حقيقي (1.9 تحت) | profile | — |
| الإدارة: جروباتي وإدارة الجروبات | قيد التنفيذ | 1.12 | — | profile | — |
| النظام: الإعدادات، ومركز الأمان | جزئي | `web/views/SettingsView.vue` (صفحة واحدة)، و`web/components/settings/SecuritySettings.vue` | أقسام من A لـ H (1.11 تحت) | identity + frontend | — |
| النظام: مركز الخصوصية | غير موجود | مفيش إعدادات «مين يقدر» في أي خدمة | 1.6 و2.3 و3.6 | graph + profile + chat | 1.6 |
| النظام: مركز المساعدة والدعم | غير موجود | `Conversation.Type.support` موجود في `svc/chat/chat/models.py` بس من غير واجهة | صفحات مساعدة ثابتة بلغتين، ومحادثة دعم بصندوق وارد للموظفين | chat + frontend | لوحة الإدارة |
| القائمة بتتغيّر حسب الصلاحيات | جزئي | `web/lib/capabilities.ts`، و`auth.isStaff` في `AppsMenu.vue`، و`web/e2e/growth.spec.ts` («without a capability there is no admin menu») | بنود حسب نوع الحساب (صاحب صفحة، معلن، صانع محتوى) | frontend + identity | 2.6 |

### 1.4 الإشعارات

| البند | الحالة | الدليل | الناقص بالظبط | الخدمة المالكة | الاعتماديات |
|---|---|---|---|---|---|
| القائمة المنسدلة ومركز الإشعارات | موجود ومختبَر | `web/components/notifications/NotificationPanel.vue`، و`web/views/NotificationsView.vue`، و`web/__tests__/notifications.spec.ts` | — | notification | — |
| الأنواع: طلب صداقة، قبوله، متابع جديد، تفاعل، تعليق، رد، إشارة، مشاركة، رسالة | موجود ومختبَر | `_KINDS` في `svc/notification/notifications/registry.py`، و`handlers.py`، و`tests/test_v2.py` | — | notification | — |
| الأنواع: دعوة جروب ومنشور جروب | قيد التنفيذ | مع 1.11 | — | notification + profile | الجروبات |
| الأنواع: نشاط الصفحات | جزئي | `page.follow` متسجّل في الـ registry، بس مفيش حد بيبعته ولا handler بيستقبله | المتابعة، والتعليقات على منشورات الصفحة، والرسائل | notification + graph + profile | 2.7 |
| الأنواع: نشاط السوق واستفسارات المنتجات | جزئي | `listing.status` شغال، و`listing.inquiry` متسجّل بس مفيش handler لحدث `marketplace.inquiry.created` | handler للاستفسار (2.18) | notification | — |
| الأنواع: فرص احترافية | غير موجود | — | الخطوة 7 | notification | الخطوة 7 |
| الأنواع: تحديثات الحملات الإعلانية | غير موجود | `ad.review` متسجّل، بس `ad.review.decided` بيستهلكه سجل التدقيق في الإدارة بس | handler للمراجعة واكتمال الحملة (2.18) | notification + ads | — |
| الأنواع: إشعارات إدارية | غير موجود | — | نوع `system.notice` بيطلّعه admin بصلاحية `admin.notices.send` | notification + admin | 8.6 (قيد التنفيذ) |
| قراءة، قراءة الكل، حذف | جزئي | `notifications/read/`، و`DELETE notifications/<id>/`، و`tests/test_cleanup.py` | الحذف مش موجود في `NotificationItem.vue` | frontend | — |
| الفلترة والتصنيفات | جزئي | السيرفر بيدعم `?category=` و`?unread=1`. الواجهة فيها «الكل» و«غير المقروء» بس (`NotificationsView.vue`) | تبويبات بالتصنيفات: اجتماعي، اتصالات، رسائل، سوق، صفحات، إعلانات | frontend | — |
| التفضيلات لكل نوع وكل قناة | جزئي | `notifications/preferences/` (in_app وpush)، و`web/components/notifications/NotificationPreferences.vue`، و`web/e2e/profile.spec.ts` | قناة الإيميل | notification | قرار مزوّد الإيميل |
| الوقت، والعدّاد، والوقت الحقيقي، ومنع التكرار، والخصوصية | موجود ومختبَر | `unread-count/`، و`svc/realtime/realtime/bridge.py`، و`aggregate_key`، و`message_previews`، و`tests/test_v2.py` | — | notification + realtime | — |
| إشعارات الإيميل | غير موجود | مفيش `send_mail` في `svc/notification` | 2.19 (ملخّص)، والقناة نفسها | notification | البند 3 (الإيميل) |

### 1.5 الرسائل

| البند | الحالة | الدليل | الناقص بالظبط | الخدمة المالكة | الاعتماديات |
|---|---|---|---|---|---|
| صندوق الوارد: الكل والمؤرشف ومحادثات الجروبات | موجود ومختبَر | `svc/chat/chat/tests/test_inbox.py`، و`web/e2e/chat.spec.ts` | — | chat | — |
| صندوق الوارد: غير المقروء | جزئي | `unread_count` لكل محادثة موجود | فلتر «غير المقروء» في القائمة | frontend | — |
| طلبات الرسائل والسبام | غير موجود | مفيش model | 3.6: طلب أول رسالة من غير الأصدقاء، وقبول ورفض، ومجلد سبام | chat | 1.6 (إعداد «مين يراسلني») |
| محادثات الأعمال (الصفحات) | جزئي | `Conversation.Type` فيه `page` و`marketplace` | صندوق وارد للصفحة جوه مدير الصفحات | chat + profile | 2.7 |
| فردي وجماعي، ووقت حقيقي، ونصوص، ورسائل صوتية، وصور، وفيديو، ومستندات | موجود ومختبَر | `svc/chat/chat/tests/test_messenger.py`، و`web/e2e/chat-features.spec.ts` | — | chat + media | — |
| الرد، والتفاعل، والتحويل، والتعديل، والحذف، والبحث | موجود ومختبَر | `MessageReaction` و`reply_to` و`forward/` و`MessageEdit` و`messages/search/` | — | chat | — |
| الكتابة الآن، والاتصال، وآخر ظهور، والقراءة، والتسليم | موجود ومختبَر | `svc/realtime/realtime/tests/test_presence.py`، و`last_read_seq` و`last_delivered_seq` | إخفاء حالة الاتصال كإعداد (1.11 B) | realtime + chat | — |
| تثبيت الرسائل | موجود ومختبَر | `PinnedMessage`، و`onPin` في `MessagesView.vue` | — | chat | — |
| تثبيت محادثة في القائمة | غير موجود | مفيش `pinned_at` على `ConversationMember` | حقل وترتيب | chat | — |
| الكتم والأرشفة | موجود ومختبَر | `conversations/<id>/mute/` و`/archive/` | — | chat | — |
| الحظر من جوه الشات | جزئي | الحظر بيجي من graph بس (`BlockedPair`) | زر حظر في لوحة التفاصيل بينادي `graphService.block` | frontend | — |
| الإبلاغ عن رسالة | غير موجود | moderation بيستهلك `message.reported`، بس chat عمره ما بعته | قرار لقطة الدليل (§0 في الـ roadmap) وبعده endpoint | chat + moderation | قرار |
| واجهة بتلات أعمدة على الكمبيوتر | جزئي | `MessagesView.vue`: شبكة `md:grid-cols-[280px_1fr]`، و`SharedMediaPanel` و`GroupPanel` لوحات بتفتح فوق الصفحة | عمود ثالث ثابت للتفاصيل والوسائط على `xl` | frontend | — |
| تنقّل مخصّص على الموبايل | موجود ومختبَر | القائمة والمحادثة بيتبدّلوا (`hidden md:flex`)، وزر رجوع | — | frontend | — |
| تجهيز المكالمات الصوتية والمرئية | موجود ومختبَر | `svc/chat/calls/`، و`web/e2e/calls.spec.ts` (مكالمة حقيقية عبر LiveKit) | رفع اليد، وتجربة TURN من شبكة موبايل | chat | — |
| صلاحيات كل محادثة ومرفق | موجود ومختبَر | `svc/chat/chat/tests/test_chat_api.py`، والوسائط الخاصة (1.5) | — | chat + media | — |

### 1.6 الملف الشخصي

| البند | الحالة | الدليل | الناقص بالظبط | الخدمة المالكة | الاعتماديات |
|---|---|---|---|---|---|
| الغلاف، والصورة، والاسم، واسم المستخدم، والنبذة | موجود ومختبَر | `web/components/profile/ProfileHero.vue`، و`UserProfile` في `svc/profile/profiles/models.py`، و`web/e2e/profile.spec.ts` | — | profile | — |
| اسم بكتابة تانية (الصورة 2) | غير موجود | — | `alt_name` اختياري | profile | — |
| شارة التوثيق | غير موجود | — | `verified_at`، ويمنحها موظف بصلاحية جديدة | profile + admin | 8.6 + قرار 5.9 |
| الموقع والموقع الإلكتروني | جزئي | `city` و`country` لهم خصوصية لكل حقل (`ProfileFieldPrivacy`)، و`UserLink` | حقل website مستقل بالشكل (2.2) | profile | 2.2 |
| المتابِعين والأصدقاء | موجود ومختبَر | `profile.followersCount` و`friendsCount` في `ProfileHero.vue` | — | graph | — |
| المتابَعين | غير موجود | `ProfileHero.vue` مش بيعرضه، ومفيش counters endpoint في graph | `AccountCounter` (1.6) | graph | 1.6 |
| أزرار الملف: صداقة، قبول، متابعة، رسالة، نسخ الرابط، حظر، تعديل | موجود ومختبَر | `web/components/social/FriendButton.vue` و`FollowButton.vue`، و`copyLink` في `ProfileHero.vue`، و`svc/graph/graph/tests/test_blocks_privacy.py` | — | graph + profile | — |
| مشاركة الملف | غير موجود | — | Web Share API، أو مشاركة كمنشور | frontend + post | — |
| الإبلاغ عن ملف | جزئي | `moderation/reports/file/` بيقبل target من نوع user | زر في قائمة «…» | frontend | — |
| التبويبات: المنشورات، الأصدقاء، الصور | موجود ومختبَر | `ProfileView.vue` (`posts` و`photos` و`friends`)، و`ProfilePhotosTab.vue` | فلترة الصور في SQL (2.5) | profile + post | 2.5 |
| تبويب «حول» | جزئي | بطاقة «نبذة» في `ProfileDetails.vue`، ومفيش تبويب | تبويب بأقسام: أساسي، عمل، تعليم، روابط، تواصل | frontend | — |
| تبويبات الفيديو والريلز | غير موجود | — | 5.7 و5.8 | post | الخطوة 5 |
| تبويب الأماكن (check-ins) | غير موجود | `Post` مفيهوش حقل مكان | حقل مكان في المنشور (الموجة 2C) | post | الموجة 2 |
| تبويب الإعجابات (لو الخصوصية تسمح) | غير موجود | — | قائمة تفاعلات المستخدم، مقفولة افتراضيًا | post | قرار خصوصية |
| تبويب إعلانات السوق | جزئي | صفحة البائع `sellers/<id>/` موجودة | `?seller_id=` وتبويب في الملف (2.5) | marketplace + frontend | 2.5 |
| تبويب المعلومات الاحترافية | جزئي | العمل والتعليم في `ProfileDetails.vue` | الـ headline (2.4)، والمهارات (7.1) | profile | 2.4، الخطوة 7 |
| «حول»: المهارات والاهتمامات | غير موجود | — | المهارات في 7.1 (D4). الاهتمامات حقل جديد | profile | الخطوة 7 |
| «حول»: معلومات التواصل حسب الخصوصية | جزئي | `contact` موجود للصفحات بس (`ContactField`) | contact للملف الشخصي، يدخل في `CONTROLLABLE_FIELDS` | profile | — |
| «حول»: الجنس (الصورة 3) | غير موجود | — | حقل اختياري، خاص افتراضيًا | profile | قرار 5.8 |
| سجل النشاط | غير موجود | — | 2.8 | profile | 2.8 |
| التحكم في ظهور الملف | موجود ومختبَر | `visibility` و`profile/me/privacy/`، و`svc/profile/profiles/privacy.py`، و`tests/test_profile_api.py` | قفل الملف و`searchable` (2.3 و1.6) | profile | — |
| زر «فلترة» المنشورات (الصورة 3) | غير موجود | — | فلترة بالسنة والنوع على `/posts/?author=` | post + frontend | — |

### 1.7 استوديو صانع المحتوى

| البند | الحالة | الدليل | الناقص بالظبط | الخدمة المالكة | الاعتماديات |
|---|---|---|---|---|---|
| لوحة مستقلة (`/studio`) | غير موجود | مفيش route | layout مستقل بتنقّل جانبي | frontend | الموجة 4 |
| إجمالي المتابعين ونموّهم | غير موجود | مفيش counters ولا تاريخ | `AccountCounter` (1.6)، ولقطة يومية | graph | 1.6 |
| المشاهدات والوصول | غير موجود | «impression» و«reach» موجودين في ads بس | تسجيل مرات ظهور المنشور (beacon) في feed، بنفس فكرة D8 | feed | الموجة 4 |
| التفاعل وأداء المحتوى وأفضل المنشورات | جزئي | العدّادات الحالية: `reaction_count`، و`PostReactionCount`، و`comment_count`، و`share_count` | تاريخ يومي، والحفظ كعدّاد، وترتيب | post | — |
| أفضل الفيديوهات، وأداء الريلز، ووقت المشاهدة | غير موجود | — | 5.12 | feed + post | الخطوة 5 |
| نظرة على الجمهور | غير موجود | — | تفصيل بالمنطقة والعمر، ويستخبى لو أقل من 10 أشخاص (5.12) | feed | الخطوة 5، 2.12 |
| إنشاء وتعديل وحذف المنشورات | موجود ومختبَر | `PATCH`/`DELETE /posts/<id>/`، و`svc/post/posts/tests/test_post_api.py` | — | post | — |
| رفع فيديو وريلز | غير موجود | 400 `video_not_supported_yet` | الخطوة 5 | post + media | الخطوة 5 |
| الجدولة | غير موجود | مفيش `publish_at` ولا مهمة نشر | `status=scheduled` و`publish_at`، ومهمة beat بـ `skip_locked` | post | L.2 (beat مستقل) |
| المسودات | غير موجود | `Post` مفيهوش حالة draft | `status=draft` | post | — |
| تقويم المحتوى (Planner) | غير موجود | — | عرض شهري (الصورة 6) | frontend + post | الجدولة |
| إدارة التعليقات | جزئي | صاحب المنشور يقدر يحذف ويغيّر `comment_policy` (`tests/test_comments_v2.py`) | صندوق تعليقات مجمّع لكل المحتوى | post + frontend | — |
| جاهزية الربح | غير موجود | `PAYMENT_VERIFICATION_AVAILABLE = False` في `svc/ads/ads/checks.py` | صفحة «جاهزية» بشروط حقيقية من غير أرباح وهمية (البند 3) | post + frontend | الدفع |
| الدخول حسب الأهلية والصلاحية | غير موجود | مفيش نوع حساب «صانع محتوى» | `profile_type=creator` (2.6) | profile | 2.6 |

### 1.8 مركز المحفوظات

| البند | الحالة | الدليل | الناقص بالظبط | الخدمة المالكة | الاعتماديات |
|---|---|---|---|---|---|
| حفظ المنشورات | موجود ومختبَر | `posts/<id>/save/`، و`test_save_unsave_idempotent` في `svc/post/posts/tests/test_post_api.py` | — | post | — |
| حفظ المنتجات والإعلانات | موجود ومختبَر | `ListingSave` في marketplace، و`web/views/SavedView.vue` (تبويب الإعلانات) | في نموذجين للحفظ (`SavedItem` بنوع listing، و`ListingSave`). لازم مصدر واحد | marketplace + post | — |
| حفظ الصفحات | جزئي | `SaveSerializer` بيقبل `page`، من غير واجهة | زر حفظ في الصفحة | frontend | — |
| حفظ الجروبات والفعاليات | غير موجود | `item_type` مفيهوش group ولا event | إضافتهم للـ enum مع فحص الرؤية | post | الجروبات |
| حفظ الفيديو والريلز | غير موجود | `video` في الـ enum، بس مفيش فيديو أصلًا | 5.9 | post | الخطوة 5 |
| المجموعات: إنشاء، إعادة تسمية، حذف، نقل | غير موجود | `SavedCollection` موجود، بس فيه المجموعة الافتراضية بس | 1.16 | post | — |
| الملاحظات والبحث | غير موجود | — | `SavedItem.note`، وبحث في العناوين المحفوظة | post | — |
| الفلترة بالنوع والترتيب بالتاريخ | جزئي | `?item_type=`، والأحدث أولًا بس | ترتيب الأقدم أولًا | post | — |
| خصوصية المحفوظات | موجود ومختبَر | كل الاستعلامات بـ `owner_id`، و`tests/test_lists.py` | — | post | — |

### 1.9 الصفحات

| البند | الحالة | الدليل | الناقص بالظبط | الخدمة المالكة | الاعتماديات |
|---|---|---|---|---|---|
| أي مستخدم مسجّل يقدر يعمل صفحة | موجود ومختبَر | `PageCreateView` في `svc/profile/profiles/views.py`، و`tests/test_profile_api.py` | — | profile | — |
| الحماية من إساءة الاستخدام | جزئي | الحد العام `tara_write` بس (120 في الدقيقة) | حد لعدد الصفحات لكل حساب، وفي اليوم، وإيميل موثّق شرط | profile | — |
| أنواع الصفحات (تجارية، علامة، شخصية عامة، …) | جزئي | `category` نص حر (CharField 80) | كتالوج تصنيفات ثابت، والنوع من ضمن 9 أنواع | profile | — |
| الحقول: الاسم، الرابط، الوصف، الموقع الإلكتروني، التواصل، الموقع | موجود ومختبَر | `Page` و`ContactField` في `svc/profile/profiles/serializers.py` | — | profile | — |
| صورة الصفحة وغلافها | جزئي | الحقلين موجودين، بس للقراءة بس في الـ API | 2.6 | profile | 2.6 |
| زر الإجراء (اتصل، راسلنا، …) | غير موجود | — | `action_button` بقائمة ثابتة | profile | — |
| الخصوصية والظهور | جزئي | `status` = draft أو published | — | profile | — |
| الأدوار الست | جزئي | `PageRole` فيه الست أدوار، بس المفروض فعلًا owner وadmin وeditor بس (`update_page` و`add_member`) | مصفوفة صلاحيات لكل دور: المشرف للتعليقات، والمحلّل للرؤى، والمعلن للترويج | profile | — |
| أكتر من مدير للصفحة | موجود ومختبَر | `pages/id/<id>/members/` | الإضافة مباشرة من غير دعوة وقبول | profile | — |
| لوحة الإدارة: نظرة عامة، المنشورات، الرؤى، الرسائل، الوسائط، التقييمات، الفعاليات، الإعلانات | غير موجود | `PageDetailView.vue` فيه التعديل والفريق بس | مدير الصفحات (الموجة 4) | profile + post + chat | 2.7 |
| النشر باسم الصفحة | جزئي | `Post.author_type` موجود، بس مفيش view بيمرّره | 2.7 | post + feed + profile | 2.7 |
| الجدولة، والرد على التعليقات والرسائل، ودعوة المتابعين، والترويج | غير موجود | — | الموجتين 4 و5، والترويج بعد 6.3 | post + chat + ads | 2.7، الدفع |
| إلغاء تنشيط الصفحة وإعادة تنشيطها (الصورة 8) | غير موجود | مفيش endpoint، و`deleted_at` محدّش بيكتبه | `deactivate` و`reactivate`، ولوحة «الصفحات المعطّلة» | profile | — |
| رابط عام وملف عام للصفحة | جزئي | `/pages/:handle` بس للمسجّلين | الصفحات العامة للزوار (قرار #10 في الـ roadmap) | frontend + edge | قرار |

### 1.10 الجروبات

| البند | الحالة | الدليل | الناقص بالظبط | الخدمة المالكة | الاعتماديات |
|---|---|---|---|---|---|
| كل قسم الجروبات (الأنواع، والإنشاء، والمميزات، والأدوار، والإدارة، واللوحة) | قيد التنفيذ | 1.11 و1.12 (مفيش app لسه على القرص وقت المراجعة) | بعد ما يخلصوا: فعاليات الجروبات (`host_type` في gatherings)، وحفظ الجروبات (1.8 فوق) | profile + post | — |

### 1.11 الإعدادات (من A لـ H)

| البند | الحالة | الدليل | الناقص بالظبط | الخدمة المالكة | الاعتماديات |
|---|---|---|---|---|---|
| **A** الاسم والإيميل وكلمة السر والموبايل | موجود ومختبَر | `SettingsView.vue`، و`ChangeEmailForm.vue` و`ChangePasswordForm.vue`، و`svc/identity/identity/tests/test_account_security.py` | — | identity + profile | — |
| **A** تغيير اسم المستخدم | جزئي | الـ handle بيتعدّل من الملف | فترة انتظار 14 يوم، وحجز الاسم القديم 30 يوم (2.2) | profile | 2.2 |
| **A** حالة الحساب، وإلغاء التنشيط، والحذف | غير موجود | `Account.Status` فيه DEACTIVATED وDELETED، بس محدّش بيكتبهم | 2.9 (إلغاء تنشيط قابل للرجوع)، وL.5 (الحذف والمسح) | identity + كل الخدمات | L.5 |
| **A** جلسات الدخول | موجود ومختبَر | `auth/sessions/`، و`test_session_list_and_revoke` | «إنهاء كل الجلسات التانية» | identity | — |
| **B** مين يشوف منشوراتي ومين يعلّق | جزئي | لكل منشور لوحده: `Audience` و`CommentPolicy` | جمهور افتراضي، وسياسة تعليق افتراضية | post + profile | — |
| **B** مين يشوف أصدقائي، ومين يبعت طلب صداقة، ومين يتابعني | غير موجود | `ensure_lists_visible` في `svc/graph/graph/services.py` مستنّي 1.6 | 1.6 | graph | 1.6 |
| **B** مين يراسلني | غير موجود | فحص الحظر بس في `svc/chat/chat/services.py` | 3.6 | chat | 1.6 |
| **B** مين يعمل لي tag | غير موجود | مفيش tagging أصلًا | مع التاج في الموجة 2C | post | الموجة 2 |
| **B** ظهور الملف | موجود ومختبَر | `profile/me/privacy/` | — | profile | — |
| **B** الظهور في محركات البحث | غير موجود | مفيش `noindex` | `allow_search_engines` (مرتبط بقرار الصفحات العامة) | profile + edge | قرار #10 |
| **B** ظهور حالة الاتصال | غير موجود | `svc/realtime/realtime/presence.py` بيعرضها للأصدقاء وأطراف المحادثات، ومينفعش تتقفل | `show_presence` | realtime + profile | — |
| **C** تغيير كلمة السر، والجلسات النشطة | موجود ومختبَر | (زي A) | — | identity | — |
| **C** التحقق بخطوتين (2FA) | غير موجود | `TwoFactorSecret` في `svc/identity/identity/models.py` scaffold بس، من غير كود TOTP | TOTP مع رموز استرداد (L.4)، وممكن يتعمل من غير بنية جديدة | identity | — |
| **C** تنبيهات الدخول والنشاط المريب | غير موجود | `SecurityEvent` بيسجّل، بس مش بينبّه | إيميل عند جهاز أو منطقة جديدة | identity | الإيميل في الإنتاج |
| **C** الأجهزة المعروفة وسجل الدخول | جزئي | `Device` و`SecurityEvent` من غير endpoint | `me/security/history/` و`me/devices/` | identity | — |
| **C** استرداد الحساب | جزئي | إعادة تعيين كلمة السر بالإيميل | رموز استرداد للـ 2FA | identity | 2FA |
| **D** push وداخل التطبيق ولكل تصنيف | موجود ومختبَر | `NotificationPreferences.vue`، و`tests/test_push.py`، وساعات الهدوء | الجروبات بعد 1.11 | notification | — |
| **D** إشعارات الإيميل | غير موجود | — | (البند 3) | notification | الإيميل |
| **E** تفضيلات الـ feed | غير موجود | `FeedItem.score` مش مستخدم، والترتيب زمني | 1.7 (لك، الأحدث، المفضلة، المتابَعين) | feed | 1.7 |
| **E** الحسابات المفضّلة والمخفية والمكتومة والمقيّدة | غير موجود | مفيش mute ولا restrict ولا favorites في graph | الموجة 2D | graph + feed | — |
| **E** المحظورين | جزئي | `GET /blocks/` موجود (`web/services/graph.ts`) من غير شاشة في الإعدادات | قائمة المحظورين وفك الحظر | frontend | — |
| **E** المحتوى الحساس والتشغيل التلقائي | غير موجود | — | التشغيل التلقائي مع الخطوة 5، والمحتوى الحساس مع وسم moderation | feed + post | الخطوة 5 |
| **F** اللغة | موجود ومختبَر | `LocaleToggle.vue`، و`account.language`، و`web/__tests__/i18n.spec.ts` | — | identity + frontend | — |
| **F** المنطقة الزمنية وصيغة التاريخ | جزئي | بتتاخد من المتصفح (`Intl…timeZone`) | إعداد صريح يتخزّن في الحساب | identity + frontend | — |
| **F** حجم الخط، وتقليل الحركة، وإمكانية الوصول | جزئي | `prefers-reduced-motion` محترم في `CommentList.vue` و`MediaTheater.vue` | إعدادات صريحة (حجم الخط، تقليل الحركة، تباين أعلى) | frontend | — |
| **G** داكن، وفاتح، وحسب النظام | موجود ومختبَر | `web/stores/ui.ts` (`Theme = light|dark|system`) | — | frontend | — |
| **H** مركز الحسابات (الهويات، وصلاحيات الصفحات) | غير موجود | `sub` في الـ JWT دايمًا هو الحساب | قائمة الصفحات اللي بديرها وأدواري، وبعدين التبديل للتصرف كصفحة | profile + identity | 2.7 |
| تأكيد آمن للإجراءات الحساسة | جزئي | ربط جوجل وفكّه، وتغيير الإيميل وكلمة السر، كلهم بيطلبوا كلمة السر الحالية | endpoint موحّد لإعادة التحقق (`reauth`) قبل الحذف وإلغاء الـ 2FA | identity | — |

### 1.12 البحث

| البند | الحالة | الدليل | الناقص بالظبط | الخدمة المالكة | الاعتماديات |
|---|---|---|---|---|---|
| البحث v2: الفهرسة، وpg_trgm، وتطبيع العربي، والصفحات، وفلترة الصلاحيات، والجروبات والفعاليات | قيد التنفيذ | 1.15 | — | search | — |
| حقل البحث، والاقتراحات، والاقتراح التلقائي | موجود ومختبَر | `AppNavbar.vue`، و`autocomplete/`، و`svc/search/searchsvc/tests/test_search.py` | — | search | — |
| البحث الأخير ومسحه | جزئي | `localStorage` بس (`tara.recentSearches`) | سجل على السيرفر لو المستخدم وافق | search | بعد 1.15 |
| البحث الرائج | غير موجود | — | من 1.8 (الرائج من المنشورات العامة بس) | search + post | 1.8 |
| التنقّل بالكيبورد | غير موجود | `AppNavbar.vue` بيستخدم `mousedown` بس، ومفيش أسهم | ARIA combobox وأسهم وEnter | frontend | — |
| تبويبات: الكل، الناس، المنشورات، المنتجات | موجود ومختبَر | `web/views/SearchView.vue` | — | frontend | — |
| تبويبات: الصور، والفيديو، والريلز | غير موجود | — | بعد الخطوة 5 (الصور ممكن تتعمل قبلها) | search | الخطوة 5 |
| تبويبات: الشركات والوظائف | غير موجود | — | الخطوة 7 | search | الخطوة 7 |

### 1.13 قائمة «إنشاء»

| البند | الحالة | الدليل | الناقص بالظبط | الخدمة المالكة | الاعتماديات |
|---|---|---|---|---|---|
| زر «إنشاء» في كل مكان | جزئي | `web/components/layout/CreateMenu.vue` (على `sm` وأكبر)، والزر الأوسط على الموبايل | الزر بيودّي لـ `/home` بدل ما يفتح محرّر موحّد في مكانه | frontend | — |
| إنشاء منشور، وعرض منتج في السوق | موجود ومختبَر | `CreateMenu.vue`، و`web/e2e/posts.spec.ts` | — | post + marketplace | — |
| إضافة قصة | غير موجود | — | 1.10 | post | 1.9 |
| رفع فيديو، وإنشاء ريلز | غير موجود | — | الخطوة 5 | post + media | الخطوة 5 |
| بث مباشر | غير موجود | — | (البند 3) | — | بنية تحتية |
| إنشاء جروب | قيد التنفيذ | — | يتضاف للقائمة لما 1.12 تخلص | frontend | الجروبات |
| إنشاء صفحة وإنشاء فعالية | جزئي | موجودين في `/pages` و`/events/new` بس مش في القائمة | روابط في القائمة | frontend | — |
| منشور احترافي | غير موجود | — | الخطوة 7 | profile | الخطوة 7 |
| المحرّر: نص، وصور متعددة، وهاشتاج، وجمهور، وصلاحيات التعليق | موجود ومختبَر | `web/components/post/CreatePostCard.vue` (لحد 10 صور، والاستطلاع)، و`tests/test_comments_v2.py` | — | post | — |
| المحرّر: فيديو | غير موجود | D1 | الخطوة 5 | post | الخطوة 5 |
| المحرّر: tag لأشخاص، ومكان، وشعور أو نشاط | غير موجود | مفيش حقول | `PostTag` بإشعار `post.tag`، و`place`، و`feeling` | post + notification | — |
| المحرّر: الجدولة والمسودات | غير موجود | — | (1.7 فوق) | post | L.2 |
| محرّر واحد في كل المنصة | جزئي | `CreatePostCard` في الرئيسية بس | `ComposerDialog` واحد يفتح من أي مكان (الملف، والصفحة، والجروب) | frontend | — |

### 1.14 الصفحة الرئيسية (Home feed)

| البند | الحالة | الدليل | الناقص بالظبط | الخدمة المالكة | الاعتماديات |
|---|---|---|---|---|---|
| العمود الشمال: اختصار الملف والتنقّل | جزئي | `LeftSidebar.vue` | (1.2 فوق) | frontend | — |
| العمود الأوسط: محرّر المنشور، والـ feed، وبطاقات المنشورات | موجود ومختبَر | `web/views/HomeView.vue`، و`svc/feed/feed/tests/test_feed.py`، و`web/__tests__/feed.spec.ts` | — | feed + post | — |
| شريط القصص | غير موجود | — | 1.10 | post | 1.9 |
| منشورات مقترحة | غير موجود | — | 1.7 (Explore) | feed | 1.7 |
| العمود اليمين: جهات الاتصال (الأصدقاء مع حالة الاتصال) | موجود ومختبَر | `web/components/layout/RightSidebar.vue`، و`web/__tests__/directory.spec.ts` | — | graph + realtime | — |
| العمود اليمين: أصدقاء مقترحين | غير موجود | مفيش suggestions في graph | 1.6 | graph | 1.6 |
| العمود اليمين: المواضيع الرائجة | غير موجود | — | 1.8 | post + search | 1.8 |
| العمود اليمين: جروبات مقترحة | قيد التنفيذ | اقتراحات الجروبات جزء من 1.11 | — | profile | — |
| العمود اليمين: صفحات مقترحة | غير موجود | — | صفحات بيتابعها أصدقائي | graph | 1.6 |
| العمود اليمين: الفعاليات | جزئي | `/events/` فيها تبويبات (going وinvited) | ويدجت «فعالياتك الجاية» | frontend | — |
| العمود اليمين: الإعلانات الممولة وأعياد الميلاد (الصورة 4) | غير موجود | الإعلان الممول جوه الـ feed بس (`SponsoredCard.vue`) | خانة إعلان في العمود، وأعياد الميلاد بعد القرار 5.3 | ads + graph + identity | قرار |
| ترتيب حسب الاهتمام، والمفضلة، والمتابَعين | غير موجود | `home_feed` بيرتّب بـ `-post_created_at` | 1.7 | feed | 1.7 |
| الأحدث، ومنشورات الأصدقاء | موجود ومختبَر | `FeedItem.Reason` (self وfriend وfollow)، و`test_feed.py` | — | feed | — |
| الصفحات المتابَعة في الـ feed | غير موجود | مفيش fan-out للصفحات | 2.7 | feed | 2.7 |
| محتوى الجروبات | قيد التنفيذ | 1.11 | — | post + feed | — |
| الإعلانات الممولة بعلامة واضحة | موجود ومختبَر | `ads_client.feed_sponsored`، و`SponsoredCard.vue`، و`web/e2e/growth.spec.ts`، و`ADS_SERVING_ENABLED` مقفول في الإنتاج | إخفاء الإعلان (زر X في الصورة 4) | ads + feed | 6.3 |
| شاشة فاضية حلوة للحسابات الجديدة | جزئي | `EmptyState` بنص `feed.empty` | اقتراحات حقيقية (أصدقاء وصفحات)، وخطوات «كمّل ملفك» | frontend | 1.6 |
| مفيش مستخدمين وهميين | موجود ومختبَر | كل القوائم من APIs حقيقية (سجل العمل، المرحلة 1) | — | — | — |
| إخفاء منشور مع «ليه مش عايز تشوف ده؟» | غير موجود | مفيش hide ولا snooze في post ولا feed | (الموجة 2A) | feed | — |
| شريط الريلز في الـ feed | غير موجود | — | الخطوة 5 | feed + post | الخطوة 5 |
| معاينة التعليقات جوه البطاقة | غير موجود | `showComments` في `PostCard.vue` بيبدأ مقفول | أول تعليق أو اتنين، ومحرّر تعليق ظاهر | post + frontend | — |

### 1.15 التجاوب والموبايل

| البند | الحالة | الدليل | الناقص بالظبط | الخدمة المالكة | الاعتماديات |
|---|---|---|---|---|---|
| تنقّل سفلي مناسب للّمس | موجود ومختبَر | `MobileBottomNavigation.vue` (`safe-area-inset-bottom`) | تبويب القائمة (1.2) | frontend | — |
| رسائل وإشعارات وإعدادات على الموبايل | موجود ومختبَر | `MessagesView.vue`، و`NotificationsView.vue`، و`SettingsView.vue` | — | frontend | — |
| السوق والملف الشخصي متجاوبين | موجود ومختبَر | `web/components/marketplace/SortSheet.vue`، و`ProfileHero.vue` | — | frontend | — |
| ريلز بملء الشاشة | غير موجود | — | 5.8 | frontend | الخطوة 5 |
| مفيش تمرير أفقي | جزئي | مفيش اختبار آلي | مشروع Playwright بمقاس موبايل يفحص `scrollWidth <= innerWidth` في كل صفحة | frontend | — |

### 1.16 الصلاحيات حسب الدور (RBAC)

| البند | الحالة | الدليل | الناقص بالظبط | الخدمة المالكة | الاعتماديات |
|---|---|---|---|---|---|
| مستخدم عادي، ومشرف منصة، ومدير عام | موجود ومختبَر | `libs/tara_common/tara_common/capabilities.py` (`ROLES`، والدور المقفول `admin`)، و`HasCapability`، و`svc/identity/identity/tests/test_capabilities.py` | — | identity + libs | — |
| صاحب صفحة ومديرها | جزئي | `PageRole` و`PageMember` (3 أدوار بس مفروضة فعلًا) | (1.9 فوق) | profile | — |
| صاحب جروب ومشرفه | قيد التنفيذ | 1.11 | — | profile | — |
| صاحب نشاط تجاري، وصانع محتوى | غير موجود | مفيش أنواع حسابات | 2.6 (`profile_type`) | profile | 2.6 |
| معلن | جزئي | `AdvertiserAccount` بيتعمل تلقائيًا، ودور `advertiser` في الصفحة مش مفروض | الإعلان باسم الصفحة | ads + profile | 2.7، 6.2 |
| الفحص على السيرفر مش في الواجهة بس | موجود ومختبَر | `web/e2e/growth.spec.ts` («…the API answers 403») | — | كل الخدمات | — |

### 1.17 العدد الإجمالي

| الحالة | العدد |
|---|---|
| موجود ومختبَر | 61 |
| جزئي | 58 |
| غير موجود | 98 |
| قيد التنفيذ | 9 |
| **المجموع** | **226** (صف لكل بند أو مجموعة بنود متقاربة) |

**الخلاصة:** الأساس قوي: الحساب، والرسائل، والإشعارات، والمنشورات، والسوق. الضعف في أربع حاجات:
- الهيكل اللي على طريقة فيسبوك (التنقّل، والأعمدة، والقائمة المصنّفة).
- أدوات صانع المحتوى والصفحات.
- مركز الإعدادات والخصوصية.
- كل حاجة فيها فيديو.

---

## 2. الفجوات مقارنةً بالصور

الأماكن المقترحة بتستخدم أسماء ملفات تارا. التصميم كله بهوية تارا: الشعار، والألوان (#6A00F4 و#A855F7 و#FF4ED8 و#0B0B1F و#E8E6FF)، والنصوص. مفيش أي اسم أو شعار أو أصل من فيسبوك.

### الصورة 2: رأس الملف الشخصي
| العنصر الناقص | مكانه في تارا |
|---|---|
| أيقونات في نص الشريط العلوي على الكمبيوتر، بخط تحت النشطة | `AppNavbar.vue`: الـ `nav` يظهر من `md` لفوق، مش `md` لحد `lg` بس |
| الاسم بكتابة تانية جنب الاسم الأساسي | `ProfileHero.vue` + حقل `alt_name` في profile |
| «X متابِع · Y متابَع» في سطر واحد | `ProfileHero.vue` + counters من graph (1.6) |
| النبذة والرابط في الجانب الآخر من الرأس | `ProfileHero.vue` (تخطيط شبكي على `lg`) |
| سطر بيانات: التصنيف · المدينة · حساب تواصل | `ProfileHero.vue` + `headline` (2.4) و`UserLink` |
| تبويبات: الكل، حول، ريلز، صور، أصدقاء، المزيد، وزر «…» | `ProfileView.vue`: تبويب «حول» دلوقتي، والريلز بعد الخطوة 5، و«المزيد» قائمة منسدلة |
| زر عائم لرسالة جديدة | `AppShell.vue`: مكوّن جديد `ComposeMessageFab.vue` |

### الصورة 3: جسم الملف الشخصي
| العنصر الناقص | مكانه في تارا |
|---|---|
| بطاقة «البيانات الشخصية» (المدينة موجودة، الجنس ناقص) | `ProfileDetails.vue` + حقل `gender` اختياري وخاص |
| «معلومات التواصل» بأيقونات الشبكات | `ProfileDetails.vue` + `contact` للملف الشخصي (حسب الخصوصية) |
| زر «فلترة» في رأس قائمة المنشورات | `ProfileView.vue` + `?year=&type=` في post |
| معاينة التعليقات جوه البطاقة، بشارة «صاحب المنشور» | `PostCard.vue` + `top_comments` في serializer المنشور |
| ملخّص التفاعلات في الجانب الآخر من شريط الإجراءات | `PostActions.vue` (الأيقونات المتراكبة موجودة جزئيًا في `ReactionsDialog`) |
| محرّر تعليق بأيقونات إيموجي وكاميرا وGIF وملصقات | `CommentInput.vue`: الإيموجي دلوقتي. الصورة في التعليق محتاجة وسائط للتعليقات في post. الـ GIF والملصقات محتاجة مزوّد (مؤجلين) |

### الصورة 4: الصفحة الرئيسية
| العنصر الناقص | مكانه في تارا |
|---|---|
| بنود الشريط الجانبي: الذكريات، الجروبات، الريلز، «الـ feeds»، «عرض المزيد» | `navItems.ts` + `LeftSidebar.vue` |
| «اختصاراتك»، وتذييل فيه الخصوصية والشروط والإعلانات | `LeftSidebar.vue` + صفحات `/legal/*` |
| أيقونات «بث مباشر» و«شعور» في المحرّر | `CreatePostCard.vue`: الشعور في الموجة 2C، والبث المباشر مستخبي (البند 3) |
| شريط القصص ببطاقة «أنشئ قصة» وسهم «التالي» | `HomeView.vue` + `StoriesRail.vue` (1.10) |
| بطاقة «ليه مش مهتم؟» بأسباب (مش مهتم، احتيال، جنسي، مزعج، مش بحب صاحب المحتوى، غير ذلك)، ومعاها: غفوة 30 يوم، وإلغاء المتابعة، والإبلاغ عن الصورة، والتراجع | `PostCard.vue` + `HideFeedbackCard.vue` + `feed/items/<id>/hide/` |
| زر X لإخفاء الإعلان الممول | `SponsoredCard.vue` + حدث `ad.hidden` في ads |
| العمود اليمين: «ممول» وبعده «أعياد الميلاد» | `RightSidebar.vue`: خانة الإعلان من `feed-slot`، وأعياد الميلاد بعد القرار 5.3 |

### الصورة 5: الـ feed مع الريلز
| العنصر الناقص | مكانه في تارا |
|---|---|
| شريط «ريلز» جوه الـ feed بأسهم | `HomeView.vue` + `ReelsRail.vue` (الخطوة 5، 5.11) |
| زر X لإخفاء المنشور في رأس البطاقة | `PostCard.vue` (نفس endpoint الإخفاء) |
| الشريط العلوي والعمود اليمين ثابتين وقت التمرير | موجود (`sticky` في `AppShell.vue`) |

### الصورة 6: أداة التخطيط (شبيهة Business Suite)
| العنصر الناقص | مكانه في تارا |
|---|---|
| لوحة داكنة بتنقّل جانبي: الرئيسية، الرؤى، المحتوى ← مكتبة المحتوى، أداة التخطيط، التفاعلات، كل الأدوات، وزر «إنشاء منشور» بقائمة | layout جديد `StudioLayout.vue` لـ `/studio` و`/pages/:handle/studio` |
| تقويم شهري للمنشورات المجدولة بصور مصغّرة ومواعيد | `StudioPlannerView.vue` + `GET /posts/scheduled/?from=&to=` |
| اليوم الحالي مميّز، والمنطقة الزمنية ظاهرة | `web/lib/eventTime.ts` (موجود للفعاليات) + إعداد المنطقة الزمنية (1.11 F) |
| أزرار: اليوم، والسابق، والتالي، والشهر، والفلترة | `StudioPlannerView.vue` (الأسهم بتنعكس في RTL) |
| «أكتر من 2 منشور…» لما اليوم يتملي، و«22 مشاهدة» على المنشور المنشور | `StudioPlannerView.vue` + مشاهدات من الموجة 4C |

### الصورة 7: الدخول
| العنصر الناقص | مكانه في تارا |
|---|---|
| بطاقة الدخول على الصفحة الرئيسية للزائر نفسها | `LandingView.vue` يستخدم بطاقة `LoginCard.vue` مستخرجة من `LoginView.vue` |
| مجموعة رسومات حوالين العنوان | `LandingView.vue`: رسومات SVG بهوية تارا (مش صور ناس) |
| زر «إنشاء حساب جديد» بشكل outline | `LoginCard.vue` |
| صف لغات في التذييل | `LandingView.vue` (العربي والإنجليزي، اللغتين الموجودتين بس) |
| إظهار وإخفاء كلمة السر، و«تذكرني» | `LoginCard.vue` + identity |

### الصورة 8: مدير الصفحات
| العنصر الناقص | مكانه في تارا |
|---|---|
| تنقّل جانبي: إنشاء صفحة، مركز الأعمال، البريد الوارد، الرؤى، استكشاف، الصفحات المتابَعة، الدعوات بعدّاد | `PagesView.vue` يبقى `PagesManagerView.vue` بـ layout جانبي |
| بطاقات «الصفحات اللي بتديرها»: الصورة، والاسم، وعدد الإشعارات والرسائل، وأزرار إنشاء منشور وترويج و«…» | `PageManageCard.vue` + `GET /pages/?managed=1` بعدّادات |
| لوحة «الصفحات المعطّلة» بزر «تنشيط» | `PagesManagerView.vue` + `pages/id/<id>/reactivate/` |
| زر إعدادات | `PageDetailView.vue` يتقسّم لـ `/pages/:handle/manage/*` |
| «الترويج» | يستخبى لحد 6.3 (التمويل). مفيش زر بيعمل حاجة وهمية |

---

## 3. العوائق الحقيقية

المواصفات بتمنع الوظائف الوهمية. البنود دي مينفعش تبقى حقيقية من غير بنية تحتية جديدة. القاعدة: **البند اللي مش جاهز يستخبى من القوائم، ومش يظهر معطّل أو «قريبًا» بأرقام وهمية.**

| الميزة | البنية التحتية المطلوبة | اللي ممكن يتبني بأمانة دلوقتي |
|---|---|---|
| **الفيديو والريلز** | حاوية `media-transcoder` (ffmpeg، حوالي 2 vCPU)، وHLS بروابط موقّعة، ومستخدم MinIO مقيّد (§5.1 في الـ roadmap)، وقرار التخزين (MinIO أو R2، #3)، وحجم السيرفر (#2). كل ده الخطوة 5 (حوالي 90 يوم، D1). القرص فيه فحص توقيع للفيديو بس (`svc/media/media_app/validation.py`)، ومفيش ffmpeg | الشكل والتنقّل بس من غير البنود. القصص بالصور (1.9 و1.10) مش محتاجة transcoding. الفيديو في الشات بيشتغل زي ما اترفع (D1) |
| **البث المباشر** | LiveKit موجود للمكالمات، بس البث للجمهور محتاج: ingress (RTMP أو WHIP)، وegress لـ HLS، وتخزين للتسجيلات، وCDN، وإشراف وقت البث، وحد لعدد المشاهدين. ده مش موجود في الـ roadmap خالص | ولا حاجة للجمهور. «بث مباشر» يستخبى من القوائم والمحرّر. ممكن نوصّي بمكالمة جماعية لحد 9 أشخاص كبديل حقيقي |
| **الإيميل للإشعارات** | identity بيبعت SMTP فعلًا (`svc/identity/config/settings.py`، وMailpit في التطوير). الإنتاج محتاج مزوّد (SMTP relay)، وSPF وDKIM وDMARC على الدومين، ومعالجة الارتداد والشكاوى، وقوالب HTML بلغتين، وقناة email في خدمة notification (مش موجودة) | إيميلات الحساب (التوثيق، وإعادة التعيين، وتنبيه الدخول من جهاز جديد) أول ما SMTP يتضبط. ملخّص الإشعارات (2.19) بعد اختيار المزوّد |
| **التحقق بخطوتين** | **مش محتاج بنية جديدة.** TOTP بـ `pyotp`، والسر متشفّر بمفتاح من البيئة في `TwoFactorSecret`، ورموز استرداد متخزّنة كـ hash، وفحص وقت إصدار التوكن (L.4). الـ 2FA بالـ SMS بس اللي محتاج مزوّد | TOTP مع رموز الاسترداد للكل، وإجباري لأدوار الموظفين، في الموجة 3C |
| **الربح والمدفوعات** | مفيش مزوّد دفع (البحث عن stripe وpaymob وpaypal وfawry ملقاش حاجة)، و`PAYMENT_VERIFICATION_AVAILABLE = False`. المطلوب: مزوّد (قرار #7)، والتحقق من الهوية (KYC)، والتحويلات للمستخدمين، والضرائب، ودفتر حسابات بالعملة الصغرى، ومراجعة قانونية | صفحة «جاهزية الربح» بشروط حقيقية محسوبة (عدد المتابعين، وعمر الحساب، والالتزام بالسياسات)، من غير أي رقم أرباح. الإعلانات تفضل مقفولة في الإنتاج (`ADS_SERVING_ENABLED`) |
| الجدولة | مش بنية جديدة، بس محتاجة beat مستقل (L.2). الـ beat دلوقتي جوه الـ worker (`-B`)، والجدول بيضيع مع كل إعادة تشغيل | الجدولة بمهمة كل دقيقة بـ `skip_locked`، ومعاها فحص تعويضي عند التشغيل يلحق المنشورات اللي فات ميعادها |
| أعياد الميلاد | تاريخ الميلاد (2.12) وإعداد خصوصيته | لا شيء قبل القرار 5.3 |
| الألعاب (Gaming) | منتج ألعاب كامل | مفيش. التبويب يتشال (قرار 5.5) |
| الإعلان في العمود اليمين | تمويل الحملات (6.3) | الخانة تتعرض من نفس `feed-slot`، وفي الإنتاج هتفضل فاضية لحد 6.3، ودي حقيقة مش عطل |

---

## 4. موجات التنفيذ

**قواعد التوزيع:**
- في كل موجة 4 مسارات، وكل مسار ليه **ملفاته لوحده**.
- لما مسارين يحتاجوا نفس الخدمة، واحد بس فيهم يملك `models.py` والـ migrations بتاعتها في الموجة دي.
- كل البنود من غير البنود قيد التنفيذ.
- الأيام أيام عمل لمهندس واحد، وشاملة الاختبارات.
- **تعريف «خلص»:**
  - backend متوصّل.
  - صلاحيات على السيرفر.
  - اختبارات pytest وvitest.
  - Playwright بالعربي والإنجليزي.
  - RTL متراجع.
  - مفيش وظيفة وهمية.

### الموجة 1: هيكل التطبيق على طريقة فيسبوك (أولًا، لأن كل حاجة بتتعلّق عليه)

| المسار | الوحدات | الملفات أو الخدمة المالكة | الأيام | اختبارات القبول |
|---|---|---|---|---|
| **1A** الشريط العلوي والقائمة الرئيسية | أيقونات في النص على الكمبيوتر بخط تحت النشطة (الرئيسية، الأصدقاء، السوق، الفعاليات، والجروبات لما تتدمج). قائمة رئيسية مصنّفة بالأقسام الثمانية، وأي بند مش مبني بيستخبى. قائمة الصورة الشخصية بالمساعدة والعرض | `web/components/layout/AppNavbar.vue`، و`AppsMenu.vue` (يبقى `MainMenu.vue`)، و`ProfileMenu.vue`، وملف جديد `web/components/layout/menuCatalog.ts` | 3 | vitest: الكتالوج بيخبّي البنود حسب `caps` ونوع الحساب، وبيخبّي الوحدات اللي مش مبنية. Playwright: الخط تحت التبويب النشط بعد التنقّل، بالعربي والإنجليزي؛ ومن غير صلاحية مفيش بند إدارة؛ والأسهم بتتنقّل في القائمة |
| **1B** الأعمدة والموبايل | الشريط الجانبي بكل البنود المبنية، و«عرض المزيد/أقل»، و«اختصاراتك» (الصفحات اللي بديرها)، وتذييل بروابط قانونية. العمود اليمين: خانة الإعلان، والطلبات، وجهات الاتصال، وفعالياتك الجاية. تنقّل الموبايل: الرئيسية، الأصدقاء، إنشاء، الإشعارات، القائمة، مع صفحة `/menu`. الزر العائم للرسائل. صفحات `/legal/terms` و`/legal/privacy` (المحتوى من المالك) | `LeftSidebar.vue`، و`navItems.ts`، و`RightSidebar.vue`، و`MobileBottomNavigation.vue`، و`AppShell.vue`، وملفات جديدة `views/MobileMenuView.vue` و`views/LegalView.vue`، والـ router (المسار ده بس هو اللي يضيف routes في الموجة دي) | 4 | Playwright بمقاس 390px: مفيش تمرير أفقي في `/home` و`/menu` و`/u/:handle`؛ والتبويب الخامس بيفتح `/menu`. vitest: «عرض المزيد» بيحفظ الحالة. من غير إعلانات العمود مفيهوش بطاقة فاضية |
| **1C** صفحة الزائر والدخول | بطاقة دخول على `/` (مستخرجة كـ `LoginCard.vue`)، وإظهار وإخفاء كلمة السر، و«تذكرني» (من غير تعليم: كوكي session؛ معلّم: 30 يوم)، وصف اللغات، ورسومات SVG بهوية تارا | `web/views/LandingView.vue`، و`LoginView.vue`، و`components/brand/AuthLayout.vue`، وملف جديد `components/auth/LoginCard.vue`. في identity: `views.py` و`cookies` للـ login بس (**من غير migration**) | 3 | pytest: `remember=false` بيرجّع `Set-Cookie` من غير `Max-Age`. Playwright: الزائر على `/` بيشوف البطاقة ويدخل ويوصل `/home`؛ والمسجّل على `/` بيتحوّل؛ وزر الإظهار بيغيّر `type` و`aria-pressed` |
| **1D** التسجيل | الاسم الأول والأخير، وتأكيد كلمة السر على السيرفر، وتاريخ الميلاد مع `is_minor` (2.12)، والموافقة على الشروط بنسختها، ومؤشر قوة كلمة السر، والتحقق الفوري من توفّر اسم المستخدم، وخطوة «كمّل ملفك» (صورة اختيارية) بعد التوثيق | identity (`models.py`، والـ migrations، و`serializers.py`، و`services.py`، و`tokens.py`)، وprofile (`GET /profile/handles/available/` بحد للطلبات، ومن غير migration)، و`web/views/RegisterView.vue`، وملف جديد `components/auth/PasswordStrength.vue` | 5 | pytest: كلمة سر مش متطابقة ترجّع 400 `password_mismatch`؛ ومن غير موافقة 400؛ وتحت السن المحدد 400 `age_below_minimum`؛ والتوكن فيه `is_minor`؛ و`handle-available` محدود ومش بيكشف حسابات محظورة. Playwright: تسجيل كامل بالعربي بالحقول الجديدة، ورسالة «الاسم محجوز» قبل الإرسال |

**مجموع الموجة 1:** حوالي 15 يوم عمل، يعني 5 أيام تقويم بأربع مسارات.

### الموجة 2: الرئيسية والـ feed والمحرّر

| المسار | الوحدات | الملفات أو الخدمة المالكة | الأيام | اختبارات القبول |
|---|---|---|---|---|
| **2A** خدمة feed | إخفاء منشور بسبب من قائمة ثابتة (`not_interested`، `spam`، `sexual`، `annoying`، `dislike_creator`، `other`)، وتراجع، وغفوة للكاتب 30 يوم، والأسباب تدخل في الترتيب. ترتيب v1 بأوضاع «لك» و«الأحدث» و«المفضلة» و«المتابَعين» (1.7 مع `redis-hot`) | `svc/feed/` كلها | 7.5 | pytest: المنشور المخفي ميرجعش في أي صفحة؛ والتراجع يرجّعه؛ والغفوة تخلص بعد 30 يوم؛ ووضع «الأحدث» مطابق للترتيب الحالي؛ والصفحة التانية من غير تكرار بعد 5 منشورات جديدة (من 1.7) |
| **2B** بطاقة المنشور والرئيسية | بطاقة «ليه مش عايز تشوف ده؟» بأزرارها، وزر X، ومعاينة التعليقات جوه البطاقة مع محرّر ظاهر، وملخّص التفاعلات، ومنتقي إيموجي في التعليق، ومبدّل وضع الـ feed، وإخفاء الإعلان | `components/post/PostCard.vue`، و`PostActions.vue`، و`CommentInput.vue`، و`SponsoredCard.vue`، و`views/HomeView.vue`، وملف جديد `HideFeedbackCard.vue` | 4 | vitest: الإخفاء والتراجع بيحافظوا على مكان البطاقة. Playwright: إخفاء بسبب، وبعدين تراجع، وبعد إعادة التحميل المنشور لسه مخفي؛ والأسهم بتنعكس في RTL |
| **2C** خدمة post والمحرّر | tag لأشخاص (`PostTag`، وإشعار `post.tag`، وإعداد «مين يعمل لي tag»)، ومكان نصي، وشعور أو نشاط، ومسودات، وجدولة (`publish_at` ومهمة beat)، و`top_comments` في الـ serializer، و`ComposerDialog` موحّد، وقائمة «إنشاء» كاملة (منشور، فعالية، صفحة، منتج، وجروب بعد الدمج) | `svc/post/posts/` (models والـ migrations والـ serializers والـ tasks)، وهاندلر في notification لـ `post.tag`، و`components/post/CreatePostCard.vue`، و`components/layout/CreateMenu.vue`، وملف جديد `components/post/ComposerDialog.vue` | 7 | pytest: المسودة مش ظاهرة لحد؛ والمجدول بيتنشر مرة واحدة حتى مع عاملين؛ والـ tag لشخص حاظرني بيرجّع 400؛ وtag بإعداد «محدش» بيتحوّل لطلب موافقة أو يترفض؛ و`top_comments` بيحترم الحظر. Playwright: جدولة منشور بعد دقيقتين، وبعدين يظهر في الـ feed |
| **2D** خدمة graph | خصوصية العلاقات والعدّادات والاقتراحات (1.6)، والكتم، والتقييد، والمفضّلة، وأحداث `relationship.muted` و`favorited` اللي feed بيستهلكها، وويدجت «أشخاص قد تعرفهم» و«صفحات مقترحة» في العمود | `svc/graph/` كلها، و`components/layout/RightSidebar.vue` (بعد 1B؛ المسار ده بس اللي بيعدّل فيه في الموجة 2) | 7 | pytest: مع `friends_list_visibility=only_me` القائمة ترجّع 404؛ والاقتراحات مفيهاش `searchable=false`؛ والمكتوم ميظهرش في feed الكاتم ومبيتبلّغش. Playwright: إرسال طلب صداقة من الويدجت |

**ملاحظة تنسيق:** 2A بيستهلك أحداث الكتم والمفضّلة من 2D. الأحداث الجديدة بتتشحن على إصدارين (قاعدة 1.0g).

### الموجة 3: الملف الشخصي، والمحفوظات، والقصص، والإعدادات، والرسائل

| المسار | الوحدات | الملفات أو الخدمة المالكة | الأيام | اختبارات القبول |
|---|---|---|---|---|
| **3A** الملف الشخصي | تبويب «حول»، والاسم البديل، والجنس الاختياري، والاهتمامات، وcontact للملف بخصوصية، وعدد المتابَعين، ومشاركة الملف والإبلاغ عنه، وزر الفلترة، وتبويب إعلانات السوق (2.5)، وسجل النشاط (2.8)، وقفل الملف (2.3) | `svc/profile/profiles/` (ماعدا الصفحات والجروبات)، و`views/ProfileView.vue`، و`components/profile/*` | 9 | pytest: `contact` مخفي عن غير الأصدقاء لما يكون friends؛ وسجل النشاط لصاحبه بس؛ وشخص محظور ياخد 404. Playwright: تبويب «حول» بالعربي، والإبلاغ، والفلترة بالسنة |
| **3B** المحفوظات والقصص | مجموعات المحفوظات (إنشاء، وتسمية، وحذف، ونقل)، والملاحظات، والبحث، والترتيب، وأنواع group وevent وpage، ومصدر واحد بدل `ListingSave` (1.16). القصص والأصدقاء المقربين (1.9 و1.10)، وشريط القصص وعارضها | `svc/post/posts/` (المحفوظات والـ audience)، وapp جديد `svc/post/stories/`، و`views/SavedView.vue`، وملفات جديدة `components/stories/*`، وإدخال الشريط في `HomeView.vue` (سطر واحد، بعد 2B) | 10 | pytest: حد تاني ميقدرش يقرأ مجموعتي (404)؛ والنقل ذرّي؛ والقصة المنتهية 404 لأي حد غير صاحبها؛ وقصة الأصدقاء المقربين مخفية عن الباقي (اختبارات 1.9). Playwright: إنشاء قصة بصورة، ومشاهدتها، والأرشيف |
| **3C** مركز الإعدادات | `SettingsView.vue` يتقسّم لـ `/settings/:section` من A لـ H. التحقق بخطوتين TOTP برموز استرداد (L.4)، وسجل الدخول والأجهزة، وتنبيه الدخول من جهاز جديد، وإلغاء التنشيط (2.9، والحذف بعد L.5)، وreauth موحّد، والمنطقة الزمنية وصيغة التاريخ وحجم الخط وتقليل الحركة، وقائمة المحظورين، وإخفاء حالة الاتصال، وشاشات الخصوصية فوق 1.6 | identity (models والـ migrations)، و`svc/realtime/realtime/presence.py` (`show_presence`)، و`views/SettingsView.vue`، وملفات جديدة `views/settings/*` و`components/settings/TwoFactor.vue` | 9 | pytest: الدخول من غير رمز TOTP مع تفعيل 2FA بيرجّع `two_factor_required`؛ ورمز الاسترداد بيشتغل مرة واحدة؛ والموظف من غير 2FA ميقدرش ياخد توكن بصلاحيات؛ و`show_presence=false` بيخلّي الأصدقاء يشوفوه «غير متصل». Playwright: تفعيل 2FA بتطبيق مولّد، والخروج، والدخول بالرمز |
| **3D** فجوات الرسائل | طلبات الرسائل ومجلد السبام (3.6)، وتثبيت محادثة، وفلتر غير المقروء، وعمود تفاصيل ثالث ثابت على `xl`، والحظر من الشات، والإبلاغ عن رسالة (بعد قرار لقطة الدليل) | `svc/chat/`، و`views/MessagesView.vue`، و`components/chat/*` | 6 | pytest: أول رسالة من غير صديق بتروح للطلبات ومبيتبعتش لها push؛ والقبول بينقلها للوارد؛ والرفض بيمنع الرسائل الجاية؛ والإبلاغ بيطلّع `message.reported` بلقطة من غير مرفقات خاصة. Playwright: قبول طلب رسالة |

### الموجة 4: الصفحات، والنشر باسم الصفحة، واستوديو صانع المحتوى، والإشعارات

| المسار | الوحدات | الملفات أو الخدمة المالكة | الأيام | اختبارات القبول |
|---|---|---|---|---|
| **4A** مركز الصفحات | صورة الصفحة وغلافها (2.6)، وكتالوج التصنيفات والأنواع، وزر الإجراء، وحد لإنشاء الصفحات، وإلغاء التنشيط وإعادته، ودعوة المديرين وقبولها، وفرض الأدوار الست، ونوع الحساب (`profile_type`)، والـ endpoint الداخلي لأعضاء الصفحة (أول يوم، عشان 4B). الواجهة: مدير الصفحات (الصورة 8) ولوحة `/pages/:handle/manage/*` | `svc/profile/profiles/` (الصفحات)، و`views/PagesView.vue` (يبقى `PagesManagerView.vue`)، و`PageDetailView.vue`، وملفات جديدة `components/pages/*` | 8 | pytest: المحلّل ميقدرش يعدّل؛ والمحرّر ميقدرش يضيف مدير؛ والصفحة المعطّلة 404 لغير الفريق وبتختفي من البحث؛ والصفحة رقم 11 في اليوم ترجّع 429. Playwright: تعطيل صفحة، وبعدين تنشيطها من لوحة «الصفحات المعطّلة» |
| **4B** النشر باسم الصفحة | 2.7: `as_page_id` مع فحص الدور، وfan-out لمتابعي الصفحة، وبطاقات صفحات بالجملة، وإشعارات نشاط الصفحة (`page.follow`، وتعليق على منشور صفحة)، ومركز الحسابات H (عرض الصفحات والأدوار، والتبديل للتصرف كصفحة) | `svc/post/posts/`، و`svc/feed/feed/handlers.py`، و`svc/notification/notifications/handlers.py`، و`components/post/ComposerDialog.vue` (منتقي الهوية)، وملف جديد `views/settings/AccountCenter.vue` | 7 | pytest: محرّر الصفحة ينشر باسمها، والمحلّل ياخد 403؛ ومتابع محظور من صاحب الصفحة ميستلمش؛ والإشعار بيروح لفريق الصفحة. Playwright: النشر كصفحة وظهوره في feed متابع |
| **4C** استوديو صانع المحتوى v1 | `StudioLayout` و`/studio`: لوحة بأرقام حقيقية (المتابعين ونموّهم من 1.6، والتفاعلات، والمشاركات، والحفظ)، ومرات الظهور والوصول من beacon (يتسجّل في feed بفكرة D8، وبيانات بالساعة واليوم)، ومكتبة المحتوى (المنشور والمسودات والمجدول من 2C)، وصندوق تعليقات مجمّع، وصفحة «جاهزية الربح» من غير أرباح | app جديد في `svc/feed/` (telemetry)، وendpoints قراءة في `svc/post/` في app جديد `insights` (يتسجّل في `config/urls.py`، وده التعارض الوحيد مع 4B ويتنسّق)، وملفات جديدة `views/studio/*` | 9 | pytest: الـ beacon بتوكن مشاهدة ومحدود لكل حساب؛ ونفس المشاهد في نفس الساعة بيتعدّ مرة واحدة؛ وصاحب المنشور بس اللي يشوف أرقامه؛ والتفصيل مخفي لو أقل من 10. Playwright: الأرقام بتزيد بعد مشاهدة حساب تاني |
| **4D** الإشعارات | ربط `listing.inquiry` و`ad.review` واكتمال الحملة (2.18)، وإشعارات إدارية (`system.notice`)، وتبويبات بالتصنيفات، والحذف من القائمة، وقناة email في التفضيلات (لما المزوّد يتحدد) | `svc/notification/` (ماعدا الهاندلرز بتاعة 4B: 4D بيكتب في ملف منفصل `handlers_commerce.py`)، و`components/notifications/*`، و`views/NotificationsView.vue` | 5 | pytest: استفسار على منتجي بيعمل إشعار واحد مجمّع؛ والإشعار الإداري محتاج `admin.notices.send`. Playwright: فلتر «السوق» بيعرض الاستفسار بس |

### الموجة 5: أداة التخطيط، والبحث الإضافي، والموبايل، وأعياد الميلاد والذكريات

| المسار | الوحدات | الملفات أو الخدمة المالكة | الأيام | اختبارات القبول |
|---|---|---|---|---|
| **5A** أداة التخطيط | التقويم الشهري والأسبوعي للمنشورات المجدولة والمنشورة (الصورة 6)، وإعادة الجدولة بالسحب، والمنطقة الزمنية، لصانع المحتوى وللصفحة | `views/studio/PlannerView.vue`، و`GET /posts/calendar/` في post | 5 | pytest: التقويم بيرجّع منشوراتي أو منشورات صفحتي بس؛ وإعادة الجدولة لماضي ترجّع 400. Playwright: نقل منشور ليوم تاني بالعربي، والأسهم معكوسة |
| **5B** إضافات البحث بعد 1.15 | البحث الرائج، وسجل على السيرفر بموافقة ومسحه، والتنقّل بالكيبورد (combobox)، وتبويب الصور | `svc/search/`، و`AppNavbar.vue` (جزء البحث بس)، و`views/SearchView.vue` | 4 | pytest: الرائج من المحتوى العام بس؛ ومسح السجل بيمسح كله. vitest: الأسهم وEnter وEscape |
| **5C** تمريرة الموبايل والتجاوب | مشاريع Playwright بمقاسات 390 و768 و1024، وفحص التمرير الأفقي في كل route، وaxe، وPull-to-refresh | `frontend/web/playwright.config.ts`، و`e2e/responsive.spec.ts`، وإصلاحات CSS صغيرة في الملفات صاحبتها | 4 | كل route بيعدّي `scrollWidth <= innerWidth` في الثلاث مقاسات وباللغتين؛ ومفيش مخالفة axe خطيرة |
| **5D** أعياد الميلاد والذكريات (بعد القرارات) | إعداد ظهور تاريخ الميلاد، وويدجت «أعياد ميلاد النهارده» للأصدقاء بس، و«في مثل هذا اليوم» من منشوراتي أنا بس | identity (endpoint داخلي بيرجّع اليوم والشهر بس لمجموعة ids)، وgraph (الأصدقاء)، وpost (الذكريات)، و`RightSidebar.vue` | 4 | pytest: السنة عمرها ما بتطلع؛ و`birthday_visibility=only_me` مبيظهرش؛ والذكريات مفيهاش منشورات اتمسحت أو اتشالت بالإشراف |

### بعد الموجات (محتاجة بنية تحتية أو خطوات من الـ roadmap)
- الخطوة 5: الفيديو، والريلز، وشريط الريلز، وتبويبات الفيديو، ورفعها من الاستوديو.
- 6.3: تمويل الإعلانات والترويج للمنشورات والصفحات.
- الخطوة 7: الشركات، والوظائف، والطلبات، والمنشور الاحترافي.
- البث المباشر: محتاج تصميم جديد خالص.

**المجموع التقريبي للموجات من 1 لـ 5:** حوالي 120 يوم عمل (15 + 25.5 + 34 + 29 + 17). مع 4 مسارات، الموجة بتاخد قد أطول مسار فيها، فالمدة حوالي 37 يوم تقويم (5 + 7.5 + 10 + 9 + 5). ده من غير الـ contingency (35–50% حسب الـ roadmap).

### ما يتاخد من QTech (قراءة بس)

الجذر: `E:\1_AdvancedPro\1-Web_Developer\1-Full_Stack Developer\1_Django\7-QTech-Solution\Qtech_company\`

| الجزء | المسار في QTech | يُستخدم في |
|---|---|---|
| شريط علوي بأيقونات في النص | `frontend\src\components\social\SocialTopBar.vue` | 1A: مرجع تخطيط بس (طريقة تخلّي التبويبات تتخلى عن الـ padding في الشاشات الضيقة) |
| غلاف الإيميل بالهوية | `backend\core\email_utils.py` (HTML بـ inline styles، والنص بيتعمل له escape) | 3C (تنبيهات الدخول)، و4D (قناة الإيميل) |
| ساعة الظهور (dwell) والـ beacon | `frontend\src\composables\useVisitorTracking.js` و`backend\core\tracking.py` | 4C: `visibilitychange` و`pagehide` وJSON Blob. **من غير** الكتابة في Postgres مع كل beacon |
| تذكيرات بعلامة «اتبعت» | `backend\tasks\tasks.py` و`backend\hr\tasks.py` | 2C: نشر المجدول، مع إضافة `skip_locked` |
| إجراءات جوه الإشعار | `frontend\src\components\social\NotificationBell.vue` | 4D |
| Pull-to-refresh وحسابات السحب في RTL | `frontend\src\mobile\components\PullToRefresh.vue` و`frontend\src\mobile\composables\useSwipeBack.js` | 5C، وعارض القصص في 3B |
| تطبيع العربي (بعد التصحيح) | `backend\core\chatbot.py` (`_norm`) | الدمج بيحصل في 1.15 (قيد التنفيذ) |
| بنّاء صفحات بالـ blocks ومنقّي HTML واختباراته | `backend\cms\blocks.py` و`backend\cms\sanitize.py` و`backend\cms\tests_pages.py` | لاحقًا لواجهات الصفحات التجارية (مش في الموجات دي) |
| ممنوع ينتقل | (§8.9 في `01-qtech-audit.md`) | التوكنات في `localStorage`، وأسماء الغرف من العميل، والتواجد المبثوث للكل، إلخ |

---

## 5. قرارات مطلوبة من المالك

| # | القرار | التوصية |
|---|---|---|
| 5.1 | نبني خط الفيديو (الخطوة 5) دلوقتي ولا لأ؟ | **لأ دلوقتي.** نخلّص الموجات من 1 لـ 4 الأول، ونحسم التخزين (#3) وحجم السيرفر (#2) بالتوازي، ونبدأ الخطوة 5 بعدها. لحد ده بنود الفيديو والريلز تستخبى |
| 5.2 | مزوّد الإيميل | SMTP relay بدومين موثّق (SPF وDKIM وDMARC)، زي Amazon SES أو Brevo، من غير SDK خاص، عشان نقدر نغيّره. ده لازم يتعمل قبل أي deploy حقيقي (§5.1 في الـ roadmap) |
| 5.3 | أعياد الميلاد | تتبني بعد 2.12. يظهر اليوم والشهر بس، والسنة متطلعش أبدًا. الإعداد الافتراضي «الأصدقاء»، ويتغيّر لـ «أنا بس». مفيش ظهور للقاصرين خارج الأصدقاء |
| 5.4 | معنى «الذكريات» | «في مثل هذا اليوم» من منشوراتي أنا بس، اللي لسه موجودة ومشالهاش الإشراف. مفيش ذكريات من محتوى الأصدقاء في النسخة الأولى. وفيه خيار إيقاف |
| 5.5 | تبويب «الألعاب» | يتشال، لأن مفيش منتج ألعاب. ونحط مكانه «الجروبات» أو «الفعاليات» |
| 5.6 | الدخول باسم المستخدم | نعم. identity يسأل profile داخليًا، بنفس حدود الطلبات، ونفس رسالة الخطأ العامة (من غير ما يكشف إن الاسم موجود) |
| 5.7 | صفحة الزائر | بطاقة الدخول تبقى على `/` نفسها، وأقسام التعريف بالمنصة تحتها. `/login` تفضل للروابط القديمة |
| 5.8 | الجنس والاسم البديل | الاتنين اختياريين، والجنس «أنا بس» افتراضيًا ومش بيدخل في الإعلانات |
| 5.9 | شارة التوثيق | يدوية بس، من موظف بصلاحية جديدة `admin.users.verify` ومتسجّلة في سجل التدقيق. مفيش توثيق مدفوع |
| 5.10 | البث المباشر | مؤجل لبعد الخطوة 5، ومستخبي من كل القوائم |
| 5.11 | أنواع الحسابات | `personal` افتراضي، و`creator` و`business` يختارهم المستخدم بنفسه من غير مراجعة. الاستوديو مفتوح للكل، والربح بس اللي محتاج أهلية |
| 5.12 | تخصيص التنقّل | يتخزّن على السيرفر في profile، عشان يتزامن بين الأجهزة، ومعاه نسخة محلية للسرعة |
| 5.13 | الإبلاغ عن رسالة خاصة | لقطة نص الرسالة المبلَّغ عنها والسياق اللي حواليها (رسالتين قبل) بس، من غير مرفقات إلا لو المبلّغ اختارها |
| 5.14 | صفحات الشروط والخصوصية | المالك يوفّر النص (أو المراجعة القانونية #6). التسجيل مستني النسخة الأولى |
