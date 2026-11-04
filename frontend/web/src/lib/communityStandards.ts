// Tara's Community Standards: what is not allowed, what reporting does and what
// moderators can decide. Plain bilingual text, like the terms and privacy pages
// (lib/legalContent.ts), and a draft pending review like them (LEGAL_IS_DRAFT).
// The report reasons and moderator actions named here are the ones the app offers.

export const STANDARDS_VERSION = "2026-11-04-draft";

export interface StandardsSection {
  id: string;
  heading: string;
  paragraphs?: string[];
  bullets?: string[];
}

export interface StandardsDocument {
  title: string;
  intro: string;
  sections: StandardsSection[];
}

const en: StandardsDocument = {
  title: "Community Standards",
  intro:
    "Tara is a place to belong. These standards describe what is not allowed on Tara, how reports work and what the Tara team can decide. They apply to profiles, Pages, groups, posts, stories, comments, messages, events and Marketplace listings.",
  sections: [
    {
      id: "respect",
      heading: "Respect people",
      bullets: [
        "No harassment or bullying: repeated unwanted contact, threats, or content meant to shame or intimidate someone.",
        "No hate: attacks on people for their religion, ethnicity, nationality, sex, gender, disability or similar traits.",
        "No content that threatens, praises or promotes violence against people.",
      ],
    },
    {
      id: "authentic",
      heading: "Be who you are",
      bullets: [
        "No fake accounts and no pretending to be another person, Page or organisation.",
        "No scams or fraud: fake giveaways, requests for passwords or card numbers, or misleading offers.",
        "No spam: repetitive or automated posting, misleading links or mass unwanted messages.",
      ],
    },
    {
      id: "safety",
      heading: "Keep everyone safe",
      bullets: [
        "No sexual content or nudity.",
        "Nothing that sexualises or endangers children. Accounts must belong to people old enough to use Tara.",
        "No sharing other people's private information without their consent.",
      ],
    },
    {
      id: "marketplace",
      heading: "Buying and selling",
      paragraphs: [
        "Listings must describe a real item honestly. Weapons, drugs, counterfeit goods, animals and anything illegal where you live may not be sold.",
      ],
    },
    {
      id: "reporting",
      heading: "Reporting",
      paragraphs: [
        "Use Report on a post, comment, message, story, profile, Page, group, event or listing. Choose the closest reason and add a few words if they help. Your report is confidential: the person you report is never told who reported them.",
        "Follow your reports in the Support inbox. It shows whether a report is still being reviewed and whether action was taken.",
      ],
    },
    {
      id: "decisions",
      heading: "What the Tara team can decide",
      bullets: [
        "Remove content that breaks these standards.",
        "Warn the person who posted it.",
        "Restrict an account or a Page, which can include a suspension until a set date.",
        "Approve content, or dismiss a report that does not break these standards.",
      ],
    },
    {
      id: "appeals",
      heading: "Asking for a review",
      paragraphs: [
        "When we remove your content, warn you or restrict your account, it appears in your Support inbox, with the reason when the team shared one. Choose Request review once per decision and explain why you think it was wrong. A moderator looks at it again, and you are notified of the outcome.",
        "If your account is suspended, signing in tells you until when.",
      ],
    },
  ],
};

const ar: StandardsDocument = {
  title: "معايير المجتمع",
  intro:
    "تارا مكان للانتماء. تشرح هذه المعايير ما هو غير مسموح به على تارا، وكيف تعمل البلاغات، وما الذي يمكن أن يقرره فريق تارا. وهي تسري على الملفات الشخصية والصفحات والمجموعات والمنشورات والقصص والتعليقات والرسائل والمناسبات وإعلانات السوق.",
  sections: [
    {
      id: "respect",
      heading: "احترم الآخرين",
      bullets: [
        "ممنوع التحرش أو التنمر: التواصل المتكرر غير المرغوب فيه، أو التهديد، أو المحتوى الذي يقصد إهانة شخص أو تخويفه.",
        "ممنوع خطاب الكراهية: مهاجمة الناس بسبب الدين أو العرق أو الجنسية أو الجنس أو الإعاقة أو ما يشبهها.",
        "ممنوع المحتوى الذي يهدد بالعنف ضد الناس أو يمجّده أو يروّج له.",
      ],
    },
    {
      id: "authentic",
      heading: "كن على حقيقتك",
      bullets: [
        "ممنوع الحسابات المزيفة وانتحال شخصية شخص آخر أو صفحة أو جهة.",
        "ممنوع الاحتيال: الهدايا الوهمية، أو طلب كلمات المرور أو أرقام البطاقات، أو العروض المضللة.",
        "ممنوع الرسائل المزعجة: النشر المتكرر أو الآلي، أو الروابط المضللة، أو الرسائل الجماعية غير المرغوب فيها.",
      ],
    },
    {
      id: "safety",
      heading: "حافظ على سلامة الجميع",
      bullets: [
        "ممنوع المحتوى الجنسي أو العري.",
        "ممنوع أي شيء يستغل الأطفال جنسيًا أو يعرّضهم للخطر. ويجب أن يكون صاحب الحساب في السن التي تسمح باستخدام تارا.",
        "ممنوع نشر المعلومات الخاصة بالآخرين دون موافقتهم.",
      ],
    },
    {
      id: "marketplace",
      heading: "البيع والشراء",
      paragraphs: [
        "يجب أن يصف الإعلان سلعة حقيقية بصدق. ولا يجوز بيع الأسلحة أو المخدرات أو السلع المقلدة أو الحيوانات أو أي شيء غير قانوني في بلدك.",
      ],
    },
    {
      id: "reporting",
      heading: "الإبلاغ",
      paragraphs: [
        "استخدم «إبلاغ» على المنشور أو التعليق أو الرسالة أو القصة أو الملف الشخصي أو الصفحة أو المجموعة أو المناسبة أو الإعلان. اختر أقرب سبب وأضف كلمات قليلة إن كانت تساعد. بلاغك سري: لا يعرف الشخص المُبلَّغ عنه أبدًا من أبلغ عنه.",
        "تابع بلاغاتك في صندوق الدعم. ستعرف هناك إن كان البلاغ ما زال قيد المراجعة وهل اتُّخذ إجراء.",
      ],
    },
    {
      id: "decisions",
      heading: "ما الذي يمكن أن يقرره فريق تارا",
      bullets: [
        "إزالة المحتوى المخالف لهذه المعايير.",
        "توجيه تحذير لمن نشره.",
        "تقييد حساب أو صفحة، وقد يشمل ذلك الإيقاف حتى تاريخ محدد.",
        "اعتماد المحتوى، أو رفض بلاغ لا يخالف هذه المعايير.",
      ],
    },
    {
      id: "appeals",
      heading: "طلب المراجعة",
      paragraphs: [
        "عندما نزيل محتوى لك أو نحذّرك أو نقيّد حسابك، يظهر القرار في صندوق الدعم، ومعه السبب إذا شاركه الفريق. اختر «طلب مراجعة» مرة واحدة لكل قرار واشرح لماذا تراه خاطئًا. يراجعه أحد المشرفين من جديد، وتصلك النتيجة في إشعار.",
        "إذا كان حسابك موقوفًا، تعرف عند تسجيل الدخول حتى متى.",
      ],
    },
  ],
};

export function standardsDocument(locale: string): StandardsDocument {
  return locale.startsWith("ar") ? ar : en;
}
