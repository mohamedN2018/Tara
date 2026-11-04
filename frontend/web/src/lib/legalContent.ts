/**
 * The text of Tara's Terms of Service and Privacy Policy, in Arabic and English.
 *
 * DRAFT pending legal review (owner decision 5.14): the operator's legal name,
 * address and contact channel, and the governing-law clause, must be confirmed
 * before these take effect. Bump the versions in `lib/legal.ts` with any change.
 *
 * Plain strings rendered as text (never as HTML), so no markup or i18n escaping.
 */
import type { LegalDocKind } from "@/lib/legal";

export interface LegalSection {
  id: string;
  heading: string;
  paragraphs?: string[];
  bullets?: string[];
}

export interface LegalDocument {
  title: string;
  intro: string;
  sections: LegalSection[];
}

type Lang = "ar" | "en";

const terms: Record<Lang, LegalDocument> = {
  en: {
    title: "Terms of Service",
    intro:
      "These Terms govern your use of Tara, a social network for people, pages, groups, events, messaging and a marketplace, offered in Egypt and the Gulf region. By creating an account or using Tara, you agree to these Terms and to our Privacy Policy. If you do not agree, do not use Tara.",
    sections: [
      {
        id: "accounts",
        heading: "1. Your account",
        paragraphs: [
          "You must be at least 13 years old to use Tara, or older where the law of your country sets a higher minimum age for using online services or for consenting to the processing of personal data. If you are under 18 (or under the age of legal majority where you live), you may use Tara only with the involvement of a parent or legal guardian who agrees to these Terms on your behalf.",
          "You agree to provide accurate information when you register, to keep it up to date, and to use one personal account. You are responsible for keeping your password secure and for everything that happens under your account. Tell us promptly if you believe someone else has accessed it.",
        ],
        bullets: [
          "Do not create an account for someone else without their permission, or impersonate any person, brand or organisation.",
          "Do not sell, transfer or share your account or its login details.",
          "Pages and groups you create are managed under your account; you are responsible for the roles you grant to others.",
        ],
      },
      {
        id: "content",
        heading: "2. Content rules",
        paragraphs: [
          "You may post content that you have the right to share. You must not use Tara to post, send or promote content or conduct that:",
        ],
        bullets: [
          "is unlawful in Egypt or in the country where you use Tara, or that promotes or facilitates illegal activity;",
          "harasses, threatens, bullies, doxxes or incites violence or hatred against any person or group;",
          "sexually exploits or endangers children, or contains sexual content involving minors in any form;",
          "contains nudity or sexually explicit material, or graphic violence shared to shock or glorify;",
          "is spam, a scam, a fake engagement scheme, malware or phishing;",
          "infringes someone else's intellectual property, privacy or publicity rights;",
          "is deliberately misleading in a way that can cause real-world harm, including impersonation and fraudulent listings;",
          "sells or advertises goods or services that are prohibited or restricted by law.",
        ],
      },
      {
        id: "moderation",
        heading: "3. Moderation and enforcement",
        paragraphs: [
          "We may review, limit the reach of, hide or remove content, and restrict or suspend features or accounts, when we reasonably believe they break these Terms, our policies or the law, or to protect users and the service. We use reports from users, automated signals and human review.",
          "Where we take action against your content or account, we will tell you what we did and why, unless doing so would be unlawful or would put someone at risk, and you may ask us to review the decision. Page and group administrators may also moderate the spaces they manage, within these Terms.",
          "You can report content, messages, profiles, pages, groups, events and listings from within Tara.",
        ],
      },
      {
        id: "ip",
        heading: "4. Intellectual property",
        paragraphs: [
          "You keep ownership of the content you post. By posting it, you grant Tara a non-exclusive, royalty-free, worldwide licence to host, store, copy, display, adapt (for example, resize or compress) and distribute it, only as needed to operate, secure and improve the service and to show it to the audience you chose. This licence ends when you delete the content or your account, except for copies others have shared with your permission, backups kept for a limited period, and content we must keep by law.",
          "The Tara name, logo, design and software belong to Tara's operator and are protected by law. You may not use them without written permission, except to refer to the service.",
          "If you believe content on Tara infringes your rights, report it with enough detail for us to identify the work and the content. We may remove infringing content and disable repeat infringers.",
        ],
      },
      {
        id: "marketplace",
        heading: "5. Marketplace, events and ads",
        paragraphs: [
          "Marketplace transactions are between buyers and sellers. Tara does not own, sell or inspect listed items and is not a party to the sale, unless we clearly say otherwise. Meet safely, and follow the law that applies to the item.",
          "Sponsored content is labelled. Advertisers are responsible for their ads and must follow our advertising policies and the law.",
        ],
      },
      {
        id: "security",
        heading: "6. Security and acceptable use",
        bullets: [
          "Do not access accounts or data without permission, or try to bypass privacy settings, rate limits or security controls.",
          "Do not scrape, crawl or collect data from Tara by automated means without our written permission.",
          "Do not interfere with or overload the service, or upload code designed to harm it or its users.",
          "Report security vulnerabilities to us responsibly and do not exploit them.",
        ],
      },
      {
        id: "termination",
        heading: "7. Suspension and termination",
        paragraphs: [
          "You may stop using Tara and ask us to delete your account at any time. We may suspend or end your access if you seriously or repeatedly break these Terms, if we are required to by law, or if your use creates risk or legal exposure for others or for Tara. Where reasonable, we will warn you first and let you download your information.",
          "Sections that by their nature should survive termination (such as intellectual property, liability and disputes) continue to apply.",
        ],
      },
      {
        id: "liability",
        heading: "8. Disclaimers and liability",
        paragraphs: [
          "We work to keep Tara available and secure, but the service is provided “as is” and may sometimes be interrupted. To the extent the law allows, Tara is not liable for content posted by users, for transactions between users, or for indirect or consequential losses. Nothing in these Terms limits rights you have under consumer-protection laws that cannot be waived.",
        ],
      },
      {
        id: "law",
        heading: "9. Changes, governing law and disputes",
        paragraphs: [
          "We may update these Terms. If a change is material, we will notify you in the app before it takes effect and, where required, ask you to accept the new version. Each version is dated, and the version you accepted is recorded with your account.",
          "These Terms are governed by the laws of the Arab Republic of Egypt, without affecting mandatory protections given to you by the law of the country where you live. We will first try to resolve any dispute with you informally. [Draft: the governing law and competent courts are to be confirmed in legal review.]",
        ],
      },
      {
        id: "contact",
        heading: "10. Contact",
        paragraphs: [
          "Questions about these Terms can be sent to the operator of Tara. [Draft: the operator's legal name, registered address and contact email will be published here before these Terms take effect.]",
        ],
      },
    ],
  },
  ar: {
    title: "شروط الخدمة",
    intro:
      "تنظّم هذه الشروط استخدامك لـ«تارا»، وهي شبكة اجتماعية للأشخاص والصفحات والمجموعات والفعاليات والمراسلة والسوق، مقدَّمة في مصر ومنطقة الخليج. بإنشاء حساب أو استخدام تارا فإنك توافق على هذه الشروط وعلى سياسة الخصوصية. إذا لم توافق، فلا تستخدم تارا.",
    sections: [
      {
        id: "accounts",
        heading: "1. حسابك",
        paragraphs: [
          "يجب ألا يقل عمرك عن 13 سنة لاستخدام تارا، أو عن السن الأعلى إذا اشترطه قانون بلدك لاستخدام الخدمات الإلكترونية أو للموافقة على معالجة البيانات الشخصية. إذا كان عمرك أقل من 18 سنة (أو أقل من سن الرشد في بلدك)، فلا يجوز لك استخدام تارا إلا بمشاركة أحد الوالدين أو الولي القانوني الذي يوافق على هذه الشروط نيابةً عنك.",
          "تلتزم بتقديم معلومات صحيحة عند التسجيل وتحديثها، وباستخدام حساب شخصي واحد. أنت مسؤول عن الحفاظ على سرية كلمة المرور وعن كل ما يحدث من خلال حسابك. أبلغنا فورًا إذا اعتقدت أن شخصًا آخر دخل إلى حسابك.",
        ],
        bullets: [
          "لا تنشئ حسابًا لشخص آخر دون إذنه، ولا تنتحل صفة أي شخص أو علامة تجارية أو جهة.",
          "لا تبع حسابك أو تنقله أو تشارك بيانات الدخول إليه.",
          "الصفحات والمجموعات التي تنشئها تُدار من خلال حسابك، وأنت مسؤول عن الأدوار التي تمنحها للآخرين.",
        ],
      },
      {
        id: "content",
        heading: "2. قواعد المحتوى",
        paragraphs: [
          "يمكنك نشر المحتوى الذي يحق لك مشاركته. ولا يجوز لك استخدام تارا لنشر أو إرسال أو الترويج لمحتوى أو سلوك:",
        ],
        bullets: [
          "مخالف للقانون في مصر أو في البلد الذي تستخدم منه تارا، أو يروّج لنشاط غير قانوني أو يسهّله؛",
          "يتضمن تحرشًا أو تهديدًا أو تنمرًا أو نشرًا لبيانات شخصية للغير، أو يحرّض على العنف أو الكراهية ضد أي شخص أو فئة؛",
          "يستغل الأطفال أو يعرّضهم للخطر، أو يتضمن محتوى جنسيًا يخص القُصَّر بأي شكل؛",
          "يتضمن عُريًا أو مواد جنسية صريحة، أو عنفًا مصوّرًا بقصد الصدمة أو التمجيد؛",
          "يمثل رسائل مزعجة أو احتيالًا أو تفاعلًا زائفًا أو برمجيات خبيثة أو تصيّدًا؛",
          "ينتهك حقوق الملكية الفكرية أو الخصوصية أو الصورة الخاصة بالغير؛",
          "مضلل عمدًا بشكل قد يسبب ضررًا فعليًا، بما في ذلك انتحال الشخصية والإعلانات الاحتيالية في السوق؛",
          "يبيع أو يعلن عن سلع أو خدمات محظورة أو مقيّدة قانونًا.",
        ],
      },
      {
        id: "moderation",
        heading: "3. الإشراف وتطبيق القواعد",
        paragraphs: [
          "يجوز لنا مراجعة المحتوى أو تقليل انتشاره أو إخفاؤه أو إزالته، وتقييد الميزات أو الحسابات أو إيقافها، إذا اعتقدنا بشكل معقول أنها تخالف هذه الشروط أو سياساتنا أو القانون، أو لحماية المستخدمين والخدمة. ونعتمد في ذلك على بلاغات المستخدمين والإشارات الآلية والمراجعة البشرية.",
          "عندما نتخذ إجراءً بحق محتواك أو حسابك، سنخبرك بما فعلناه وسببه، ما لم يكن ذلك مخالفًا للقانون أو يعرّض أحدًا للخطر، ويحق لك طلب مراجعة القرار. ويجوز لمديري الصفحات والمجموعات الإشراف على المساحات التي يديرونها في حدود هذه الشروط.",
          "يمكنك الإبلاغ عن المحتوى والرسائل والملفات الشخصية والصفحات والمجموعات والفعاليات والإعلانات من داخل تارا.",
        ],
      },
      {
        id: "ip",
        heading: "4. الملكية الفكرية",
        paragraphs: [
          "تظل مالكًا للمحتوى الذي تنشره. وبنشره تمنح تارا ترخيصًا غير حصري ومجانيًا وعالميًا لاستضافته وتخزينه ونسخه وعرضه وتكييفه (مثل تغيير الحجم أو الضغط) وتوزيعه، بالقدر اللازم فقط لتشغيل الخدمة وتأمينها وتحسينها ولعرضه على الجمهور الذي اخترته. وينتهي هذا الترخيص عند حذفك للمحتوى أو لحسابك، باستثناء ما شاركه الآخرون بإذنك، والنسخ الاحتياطية المحفوظة لمدة محدودة، وما يلزمنا القانون بالاحتفاظ به.",
          "اسم تارا وشعارها وتصميمها وبرمجياتها مملوكة للجهة المشغّلة لتارا ومحمية قانونًا، ولا يجوز استخدامها دون إذن كتابي، إلا للإشارة إلى الخدمة.",
          "إذا اعتقدت أن محتوى على تارا ينتهك حقوقك، فأبلغ عنه بتفاصيل كافية لتحديد العمل والمحتوى. ويجوز لنا إزالة المحتوى المخالف وإيقاف حسابات من يكرر المخالفة.",
        ],
      },
      {
        id: "marketplace",
        heading: "5. السوق والفعاليات والإعلانات",
        paragraphs: [
          "معاملات السوق تتم بين البائع والمشتري. تارا لا تملك السلع المعروضة ولا تبيعها ولا تفحصها، وليست طرفًا في البيع ما لم نذكر خلاف ذلك صراحةً. التقِ بالطرف الآخر بأمان، والتزم بالقانون المنطبق على السلعة.",
          "المحتوى المموَّل يحمل علامة واضحة. والمعلنون مسؤولون عن إعلاناتهم، وعليهم الالتزام بسياسات الإعلان لدينا وبالقانون.",
        ],
      },
      {
        id: "security",
        heading: "6. الأمان والاستخدام المقبول",
        bullets: [
          "لا تدخل إلى حسابات أو بيانات دون إذن، ولا تحاول تجاوز إعدادات الخصوصية أو حدود الطلبات أو ضوابط الأمان.",
          "لا تجمع بيانات من تارا بوسائل آلية دون إذن كتابي منا.",
          "لا تعطّل الخدمة أو تثقل عليها، ولا ترفع برمجيات تهدف إلى الإضرار بها أو بمستخدميها.",
          "أبلغنا عن الثغرات الأمنية بشكل مسؤول ولا تستغلها.",
        ],
      },
      {
        id: "termination",
        heading: "7. الإيقاف وإنهاء الحساب",
        paragraphs: [
          "يمكنك التوقف عن استخدام تارا وطلب حذف حسابك في أي وقت. ويجوز لنا إيقاف وصولك أو إنهاؤه إذا خالفت هذه الشروط مخالفة جسيمة أو متكررة، أو إذا ألزمنا القانون بذلك، أو إذا تسبب استخدامك في خطر أو مسؤولية قانونية على الآخرين أو على تارا. وحيثما كان ذلك معقولًا، سننبهك أولًا ونتيح لك تنزيل معلوماتك.",
          "تظل سارية بعد الإنهاء البنود التي يقتضي طبيعتها ذلك، مثل الملكية الفكرية والمسؤولية والنزاعات.",
        ],
      },
      {
        id: "liability",
        heading: "8. إخلاء المسؤولية وحدودها",
        paragraphs: [
          "نعمل على إبقاء تارا متاحة وآمنة، لكن الخدمة مقدَّمة «كما هي» وقد تنقطع أحيانًا. وفي الحدود التي يسمح بها القانون، لا تتحمل تارا المسؤولية عن المحتوى الذي ينشره المستخدمون، ولا عن المعاملات بينهم، ولا عن الخسائر غير المباشرة أو التبعية. ولا يحدّ أي شيء في هذه الشروط من حقوقك المقررة في قوانين حماية المستهلك التي لا يجوز التنازل عنها.",
        ],
      },
      {
        id: "law",
        heading: "9. التعديلات والقانون الحاكم والنزاعات",
        paragraphs: [
          "يجوز لنا تحديث هذه الشروط. وإذا كان التعديل جوهريًا، فسنخطرك داخل التطبيق قبل سريانه، ونطلب موافقتك على النسخة الجديدة حيثما لزم ذلك. كل نسخة مؤرخة، والنسخة التي وافقت عليها مسجلة مع حسابك.",
          "تخضع هذه الشروط لقوانين جمهورية مصر العربية، دون المساس بالحماية الإلزامية التي يمنحها لك قانون بلد إقامتك. وسنحاول أولًا حل أي نزاع معك وديًا. [مسودة: القانون الحاكم والمحاكم المختصة يُحددان بعد المراجعة القانونية.]",
        ],
      },
      {
        id: "contact",
        heading: "10. التواصل",
        paragraphs: [
          "يمكن توجيه الأسئلة حول هذه الشروط إلى الجهة المشغّلة لتارا. [مسودة: سيُنشر هنا الاسم القانوني للجهة المشغّلة وعنوانها المسجل وبريد التواصل قبل سريان هذه الشروط.]",
        ],
      },
    ],
  },
};

const privacy: Record<Lang, LegalDocument> = {
  en: {
    title: "Privacy Policy",
    intro:
      "This Policy explains what personal data Tara collects, why, how long we keep it, who we share it with and the choices and rights you have. We process personal data in line with applicable law, including Egypt's Personal Data Protection Law (Law No. 151 of 2020) and the data protection laws of the Gulf countries where Tara is offered, such as Saudi Arabia's Personal Data Protection Law and the UAE's Federal Decree-Law No. 45 of 2021.",
    sections: [
      {
        id: "collect",
        heading: "1. Data we collect",
        bullets: [
          "Account data: your name, username, email address, password (stored only as a secure hash), language, and, if you add them, a phone number, date of birth, and profile and cover photos.",
          "Content you create: posts, comments, reactions, messages, voice notes, photos and files, pages, groups, events, marketplace listings, saved items and reports.",
          "Connections: friends, follows, blocks, group and page memberships and roles.",
          "Technical data: device and browser type, IP address, sign-in sessions, security events (such as sign-ins from new devices), and diagnostic logs.",
          "Usage data: how features are used, such as notifications read and ads shown or clicked, measured in a way that does not reveal your identity to advertisers.",
          "Data from others: when you sign in with Google, we receive your name, email address and Google account identifier; other users may also mention or tag you.",
        ],
      },
      {
        id: "purposes",
        heading: "2. Why we use it",
        bullets: [
          "To provide Tara: create your account, show your profile, deliver your posts and messages to the people you choose, and run pages, groups, events and the marketplace (performance of our contract with you).",
          "To keep Tara safe: verify accounts, detect spam, fraud and abuse, enforce our Terms, and protect your account (our legitimate interests and legal obligations).",
          "To personalise your feed, suggestions and notifications, and to measure and improve features (our legitimate interests; you can change many of these in Settings).",
          "To show sponsored content, without selling your personal data and without using sensitive data for ad targeting (our legitimate interests, or your consent where the law requires it).",
          "To communicate with you about your account, security and changes to our terms (contract and legal obligations).",
          "To comply with the law and respond to valid legal requests.",
        ],
      },
      {
        id: "sharing",
        heading: "3. Who we share it with",
        paragraphs: [
          "We do not sell your personal data. We share it only: with the people and audiences you choose; with service providers who host, store, deliver email or provide infrastructure for us under contracts that require them to protect it; with advertisers as aggregate, non-identifying reports; with authorities when the law requires it or to prevent serious harm; and with a successor if Tara's operator is reorganised or acquired, subject to this Policy.",
          "Some providers may process data outside your country. When that happens we use the safeguards the applicable law requires.",
        ],
      },
      {
        id: "retention",
        heading: "4. How long we keep it",
        bullets: [
          "Account and profile data: for as long as your account exists.",
          "Content: until you delete it or your account; removed content may remain in backups for a limited period before being overwritten.",
          "Sign-in sessions: a session lasts up to 30 days unless you sign out or revoke it sooner.",
          "Security and moderation records: for as long as needed to protect the service and meet legal obligations, then deleted or anonymised.",
          "When you delete your account, we delete or anonymise your personal data within a reasonable period, except where the law requires us to keep it.",
        ],
      },
      {
        id: "rights",
        heading: "5. Your rights and choices",
        paragraphs: [
          "Depending on the law where you live, you have the right to:",
        ],
        bullets: [
          "know what personal data we hold about you and get a copy of it (data export);",
          "correct inaccurate data, most of which you can edit yourself in your profile and Settings;",
          "delete your account and personal data;",
          "object to or restrict certain processing, and withdraw consent you gave at any time;",
          "control who can see your content, contact you and find you, using your privacy settings and audience choices;",
          "complain to the data protection authority in your country, such as Egypt's Personal Data Protection Center.",
        ],
      },
      {
        id: "cookies",
        heading: "6. Cookies and local storage",
        paragraphs: [
          "Tara uses essential cookies and your browser's local storage to keep you signed in, protect your session and remember preferences such as language, theme and the layout of menus. We do not use third-party advertising cookies. If you use Google sign-in, Google may set its own cookies under its own policy. Blocking essential storage may stop Tara from working properly.",
        ],
      },
      {
        id: "security",
        heading: "7. Security",
        paragraphs: [
          "We protect your data with encryption in transit, hashed passwords, short-lived access tokens, rotating sign-in sessions with reuse detection, access controls for staff with audited actions, and rate limits against abuse. No system is perfectly secure; if a breach affects your personal data, we will notify you and the authorities as the law requires.",
        ],
      },
      {
        id: "children",
        heading: "8. Children",
        paragraphs: [
          "Tara is not for children under 13 (or the higher minimum age in your country). If we learn that such a child has an account, we will delete it. Parents or guardians who believe a child has given us data can contact us to have it removed.",
        ],
      },
      {
        id: "changes",
        heading: "9. Changes to this Policy",
        paragraphs: [
          "We will update this Policy as Tara changes. Each version is dated. If a change is material, we will tell you in the app before it takes effect.",
        ],
      },
      {
        id: "contact",
        heading: "10. Contact",
        paragraphs: [
          "To exercise your rights or ask about this Policy, contact the operator of Tara. [Draft: the operator's legal name, registered address, contact email and, where required, the data protection officer's details will be published here before this Policy takes effect.]",
        ],
      },
    ],
  },
  ar: {
    title: "سياسة الخصوصية",
    intro:
      "توضح هذه السياسة البيانات الشخصية التي تجمعها تارا، وأسباب جمعها، ومدة الاحتفاظ بها، ومن نشاركها معه، والخيارات والحقوق المتاحة لك. ونعالج البيانات الشخصية وفق القانون المنطبق، بما في ذلك قانون حماية البيانات الشخصية المصري (القانون رقم 151 لسنة 2020)، وقوانين حماية البيانات في دول الخليج التي تُقدَّم فيها تارا، مثل نظام حماية البيانات الشخصية في المملكة العربية السعودية والمرسوم بقانون اتحادي رقم 45 لسنة 2021 في الإمارات.",
    sections: [
      {
        id: "collect",
        heading: "1. البيانات التي نجمعها",
        bullets: [
          "بيانات الحساب: الاسم واسم المستخدم والبريد الإلكتروني وكلمة المرور (تُخزَّن كقيمة مشفّرة غير قابلة للاسترجاع فقط) واللغة، وإن أضفتها: رقم الهاتف وتاريخ الميلاد وصورة الملف وصورة الغلاف.",
          "المحتوى الذي تنشئه: المنشورات والتعليقات والتفاعلات والرسائل والرسائل الصوتية والصور والملفات والصفحات والمجموعات والفعاليات وإعلانات السوق والعناصر المحفوظة والبلاغات.",
          "العلاقات: الأصدقاء والمتابعات والحظر وعضويات المجموعات والصفحات وأدوارها.",
          "البيانات التقنية: نوع الجهاز والمتصفح وعنوان IP وجلسات الدخول والأحداث الأمنية (مثل الدخول من جهاز جديد) وسجلات التشخيص.",
          "بيانات الاستخدام: طريقة استخدام الميزات، مثل الإشعارات المقروءة والإعلانات المعروضة أو التي نُقر عليها، وتُقاس بطريقة لا تكشف هويتك للمعلنين.",
          "بيانات من الغير: عند الدخول بحساب جوجل نستلم اسمك وبريدك الإلكتروني ومعرّف حسابك لدى جوجل، وقد يذكرك مستخدمون آخرون أو يُشيرون إليك.",
        ],
      },
      {
        id: "purposes",
        heading: "2. أغراض الاستخدام",
        bullets: [
          "تقديم الخدمة: إنشاء حسابك وعرض ملفك وإيصال منشوراتك ورسائلك لمن تختارهم وتشغيل الصفحات والمجموعات والفعاليات والسوق (تنفيذ العقد بيننا).",
          "الحفاظ على أمان تارا: توثيق الحسابات وكشف الرسائل المزعجة والاحتيال وإساءة الاستخدام وتطبيق الشروط وحماية حسابك (مصلحتنا المشروعة والتزاماتنا القانونية).",
          "تخصيص الصفحة الرئيسية والاقتراحات والإشعارات، وقياس الميزات وتحسينها (مصلحتنا المشروعة، ويمكنك تغيير كثير من ذلك من الإعدادات).",
          "عرض المحتوى المموَّل دون بيع بياناتك الشخصية ودون استخدام البيانات الحساسة في استهداف الإعلانات (مصلحتنا المشروعة، أو موافقتك حيث يشترطها القانون).",
          "التواصل معك بشأن حسابك والأمان والتغييرات على الشروط (العقد والالتزامات القانونية).",
          "الالتزام بالقانون والاستجابة للطلبات القانونية الصحيحة.",
        ],
      },
      {
        id: "sharing",
        heading: "3. مع من نشارك البيانات",
        paragraphs: [
          "لا نبيع بياناتك الشخصية. ونشاركها فقط: مع الأشخاص والجمهور الذي تختاره؛ ومع مزودي الخدمات الذين يستضيفون البيانات أو يخزنونها أو يرسلون البريد أو يوفرون البنية التقنية لنا بموجب عقود تلزمهم بحمايتها؛ ومع المعلنين في صورة تقارير مجمّعة لا تحدد الهوية؛ ومع السلطات عندما يلزمنا القانون أو لمنع ضرر جسيم؛ ومع أي جهة تخلف الجهة المشغّلة لتارا عند إعادة الهيكلة أو الاستحواذ، مع الالتزام بهذه السياسة.",
          "قد يعالج بعض المزودين البيانات خارج بلدك، وفي هذه الحالة نطبق الضمانات التي يشترطها القانون المنطبق.",
        ],
      },
      {
        id: "retention",
        heading: "4. مدة الاحتفاظ",
        bullets: [
          "بيانات الحساب والملف الشخصي: طوال وجود حسابك.",
          "المحتوى: حتى تحذفه أو تحذف حسابك، وقد يبقى المحتوى المحذوف في النسخ الاحتياطية لمدة محدودة قبل استبداله.",
          "جلسات الدخول: تستمر الجلسة حتى 30 يومًا ما لم تسجّل الخروج أو تُلغها قبل ذلك.",
          "سجلات الأمان والإشراف: للمدة اللازمة لحماية الخدمة والوفاء بالالتزامات القانونية، ثم تُحذف أو تُجهَّل.",
          "عند حذف حسابك نحذف بياناتك الشخصية أو نجهّلها خلال مدة معقولة، إلا ما يلزمنا القانون بالاحتفاظ به.",
        ],
      },
      {
        id: "rights",
        heading: "5. حقوقك وخياراتك",
        paragraphs: [
          "بحسب القانون المنطبق في بلدك، يحق لك:",
        ],
        bullets: [
          "معرفة البيانات الشخصية التي نحتفظ بها عنك والحصول على نسخة منها (تصدير البيانات)؛",
          "تصحيح البيانات غير الدقيقة، ويمكنك تعديل معظمها بنفسك من ملفك الشخصي والإعدادات؛",
          "حذف حسابك وبياناتك الشخصية؛",
          "الاعتراض على بعض أوجه المعالجة أو تقييدها، وسحب موافقتك في أي وقت؛",
          "التحكم في من يرى محتواك ومن يتواصل معك ومن يجدك، من خلال إعدادات الخصوصية واختيار الجمهور؛",
          "تقديم شكوى إلى جهة حماية البيانات في بلدك، مثل مركز حماية البيانات الشخصية في مصر.",
        ],
      },
      {
        id: "cookies",
        heading: "6. ملفات تعريف الارتباط والتخزين المحلي",
        paragraphs: [
          "تستخدم تارا ملفات تعريف ارتباط ضرورية والتخزين المحلي في متصفحك لإبقائك مسجّل الدخول وحماية جلستك وتذكّر تفضيلاتك مثل اللغة والمظهر وشكل القوائم. ولا نستخدم ملفات تعريف ارتباط إعلانية من أطراف ثالثة. وإذا استخدمت الدخول بحساب جوجل، فقد تضع جوجل ملفاتها الخاصة وفق سياستها. وقد يؤدي حظر التخزين الضروري إلى تعطل بعض وظائف تارا.",
        ],
      },
      {
        id: "security",
        heading: "7. الأمان",
        paragraphs: [
          "نحمي بياناتك بالتشفير أثناء النقل، وتخزين كلمات المرور كقيم مشفّرة، ورموز دخول قصيرة العمر، وجلسات دخول متجددة مع كشف إعادة الاستخدام، وضوابط وصول للموظفين مع تسجيل إجراءاتهم، وحدود للطلبات ضد إساءة الاستخدام. ولا يوجد نظام آمن تمامًا؛ وإذا تأثرت بياناتك الشخصية باختراق، فسنخطرك ونخطر الجهات المختصة وفق ما يشترطه القانون.",
        ],
      },
      {
        id: "children",
        heading: "8. الأطفال",
        paragraphs: [
          "تارا ليست موجهة للأطفال دون 13 سنة (أو دون السن الأعلى المحدد في بلدك). وإذا علمنا بوجود حساب لطفل في هذه السن فسنحذفه. ويمكن للوالدين أو الأولياء الذين يعتقدون أن طفلًا قدّم لنا بيانات التواصل معنا لحذفها.",
        ],
      },
      {
        id: "changes",
        heading: "9. التعديلات على هذه السياسة",
        paragraphs: [
          "سنحدّث هذه السياسة مع تطور تارا، وكل نسخة مؤرخة. وإذا كان التعديل جوهريًا، فسنخبرك داخل التطبيق قبل سريانه.",
        ],
      },
      {
        id: "contact",
        heading: "10. التواصل",
        paragraphs: [
          "لممارسة حقوقك أو للاستفسار عن هذه السياسة، تواصل مع الجهة المشغّلة لتارا. [مسودة: سيُنشر هنا الاسم القانوني للجهة المشغّلة وعنوانها المسجل وبريد التواصل، وبيانات مسؤول حماية البيانات حيث يلزم، قبل سريان هذه السياسة.]",
        ],
      },
    ],
  },
};

export const legalContent: Readonly<Record<LegalDocKind, Record<Lang, LegalDocument>>> = { terms, privacy };

/** The document in the reader's language (Arabic unless English is chosen). */
export function legalDocument(kind: LegalDocKind, locale: string): LegalDocument {
  return legalContent[kind][locale === "en" ? "en" : "ar"];
}
