# Test dataset seeder / مولّد بيانات الاختبار

`seed_dataset.py` fills a **local** Tara stack with a large, realistic dataset so
you can browse the site with full accounts, pages and groups, and later test
feed and reels ranking. Everything goes through the real public API (`/api/v1`),
the same calls the web app makes. Nothing is written to a database directly.

`seed_dataset.py` بيملا نسخة Tara **المحلية** ببيانات كتير وواقعية، عشان تجرّب
الموقع بحسابات وصفحات وجروبات كاملة، وبعدين تختبر خوارزميات ترتيب الفيد والريلز.
كل حاجة بتتعمل من خلال الـ API الحقيقي (`/api/v1`)، نفس الطلبات اللي الواجهة
بتعملها، ومفيش أي كتابة مباشرة في قاعدة البيانات.

---

## English

### What it creates

| Item | How |
|---|---|
| ~120 accounts | Full sign-up (first/last name, date of birth, gender, consent to the current legal versions, language, theme, handle), verified with the link read from **Mailpit**, then a profile with avatar, cover, bio, city, work and education. |
| Friendships and follows | Preferential attachment: a few popular people, a long tail. |
| 19 topic pages | From the folder names (سياسة, تاريخ, قرآن, رياضة, تكنولوجيا, هواتف سامسونج / شاومي, منتجات...), each with an avatar, a cover, a team (owner, admin, editors, sometimes a moderator) and followers. |
| 8 groups | Public and private, with members, an admin and a moderator. |
| Posts | Single photos and albums (page and personal), text posts whose captions come from the video file names (view/reaction counters stripped), hashtags, feelings, locations, group posts. |
| Every other usable image | An extra pass (`phase_extra_posts`, part of `posts`) posts what the topic folders leave out: the loose screenshots at the top of the tree, `MyFilter`, `WorkShop`, `Problime`, `Tools`, `error`, `Pc Tester`, `Logo` and the project sub-folders `BackupData`, `login`, `New folder`, `New folder (2)`, plus full-page screenshots shown cropped (top part). Its post keys come from the files, so it never changes what the first pass planned. |
| Videos and reels | Every usable clip is uploaded with `purpose=post`, transcoded by media, then `POST /reels/eligibility/` decides: eligible clips (portrait 9:16, at most 90 s, as measured after transcoding) become **reels**, `reel_not_vertical` / `reel_too_long` become **video posts**. The file name never decides. The Instagram recitations go to the recitation page. |
| Marketplace | Listings from `Product/*` photos with plausible EGP prices, the burger/chicken menus from the `.xlsx` files (real menu prices), and a few phones. |
| Stories | Photo and text stories for about a third of the accounts (they expire after 24 h; re-run the `stories` phase to refresh them). |
| Engagement | Reactions, comments and replies, shares, saves, "not interested" hides, reel views, listing views and saves, story views. Popular items (the `1.2M views · 20K reactions` in a clip's name sets its weight) get much more than the long tail, and active accounts act more, so ranking has signal. |

### What it never uses

- The `Certificate` folder.
- Screenshots that can show private data or secrets: mail, chats, banking, code
  editors (Visual Studio Code), terminals and `root@` shells, browser DevTools, deploy
  dashboards (Dokploy), Task Manager, account/profile pages, CVs (also a CV saved as a photo).
- PDFs, `.ai`, `.psd`, `.rar`, `.ico`, `.svg`, `desktop.ini`, and names that look like personal documents.
- Personal phone-camera clips (`IMG_nnnn.MOV`) and the Windows Settings screen recording.
- Live conflict footage (the `إران` folder) and clips whose caption is graphic, about strikes, or inflammatory about peoples, faiths or named people.
- Videos over 200 MB (media's limit), images smaller than 160 px, and byte-identical duplicates.

Images are re-encoded to JPEG (EXIF/GPS stripped, AVIF converted) into `.seed-state/cache`.
Generated avatars are abstract shapes in Tara colours: no real person's face is used as a
fake account's avatar.

### Run

```bash
# 1) Plan only: what would be used, skipped and why, and a local ffprobe guess
python scripts/seed/seed_dataset.py \
  --source "frontend/Desgin/Captures/داتا" \
  --source "D:/2_Mieda/Instagram=quran" \
  --dry-run -v

# 2) A small trial
python scripts/seed/seed_dataset.py --source ... --source ... --accounts 8 --limit 2

# 3) The full dataset (takes 1-3 hours, mostly video transcoding); resumable
python -u scripts/seed/seed_dataset.py --source ... --source ... > .seed-state/run.log 2>&1

# Counts so far
python scripts/seed/seed_dataset.py --source x --report
```

`PATH=topic` gives the loose files of a source folder a topic (`quran` for the
recitation clips). The `داتا` tree is read by its own folder layout.

| Option | Default | Meaning |
|---|---|---|
| `--api` | `http://127.0.0.1:8080/api/v1` | Gateway |
| `--mailpit` | `http://127.0.0.1:8026/api/v1` | Mailpit API (verification links) |
| `--accounts` | `120` | Number of accounts |
| `--password` | `Seed-Tara-2026!` (or `TARA_SEED_PASSWORD`) | Password of every seed account |
| `--limit` | `0` (none) | Cap each content phase, for trials |
| `--phases` | all | `graph,pages,groups,posts,videos,listings,stories,engagement` |
| `--max-transcoding` | `2` | Videos waiting for the transcoder at once (throttle) |
| `--workers` | `4` | Parallel API calls |
| `--dry-run` | | Scan and plan, no network |
| `--allow-remote` | | Needed for any host that is not local; prints a content-rights warning |
| `--synthetic-label` | `seed-dataset` | Tara Intelligence registry label of the seed accounts (must start with `seed-`; empty skips) |
| `--register-synthetic` | | Only register the accounts already in the manifest as synthetic, then exit |

### Never production; synthetic accounts

The script exits before doing anything (even `--dry-run`) when `TARA_ENV=production`
or when `--api` is the production domain (`DOMAIN` from the environment or from
`.env_prod`; only that key is read). No flag overrides it.

Right after the accounts phase, every seed account is registered as **synthetic**
with Tara Intelligence (feed's `intel_register_synthetic --label seed-dataset --ids ...`,
through `docker compose exec`; feed needs `INTEL_ACCEPT_SYNTHETIC=true`), so its activity never mixes with real
analytics. The ids are also written to `.seed-state/synthetic-accounts.json`; if
feed does not have the command yet, register later with
`python scripts/seed/seed_dataset.py --source x --register-synthetic`.

### Idempotent and resumable

`.seed-state/manifest.json` (gitignored) records every account, page, group, post,
video, listing, story and interaction created. A re-run skips them; an interrupted
run resumes, including videos still being transcoded. Creates also send an
`Idempotency-Key`, so a request retried after a crash does not create a duplicate.
Delete `.seed-state/` only together with a fresh database.

### Logging in

Accounts are `seed.<handle>.<nnn>@example.com` with the seed password, e.g.
`seed.esraa_elsayed.001@example.com`. The manifest lists them all; the most
popular ones own the pages.

### Content rights

The source clips and photos belong to their owners (news channels, reciters,
shops). This is for a **local** development stack only. The script refuses a
non-local API unless `--allow-remote` is passed, and even then do not use it on a
public server.

---

## العربي

### بيعمل إيه

- **~120 حساب** بتسجيل كامل: الاسم الأول والأخير، تاريخ الميلاد، النوع، الموافقة
  على الشروط، اللغة والثيم واسم المستخدم. التفعيل بيتم بلينك التفعيل اللي بنقراه
  من **Mailpit**، وبعدين بروفايل كامل: صورة شخصية، غلاف، نبذة، مدينة، شغل ودراسة.
- **صداقات ومتابعات** فيها ناس مشهورة قليلة وذيل طويل من الناس العادية.
- **19 صفحة** متقسمة حسب أسماء الفولدرات (سياسة، تاريخ، قرآن، رياضة، تكنولوجيا،
  هواتف سامسونج/شاومي، منتجات...). كل صفحة ليها صورة وغلاف وفريق إدارة (مالك،
  أدمن، محررين، وأحيانًا مشرف) ومتابعين.
- **8 جروبات** عامة وخاصة، فيها أعضاء وأدمن ومشرف.
- **منشورات**: صورة واحدة وألبومات، ومنشورات نصية الكابشن بتاعها جاي من أسماء
  ملفات الفيديو بعد ما نشيل عداد المشاهدات والتفاعلات، وكمان هاشتاجات ومشاعر
  وأماكن ومنشورات جوه الجروبات.
- **فيديوهات وريلز**: كل فيديو بيترفع وبيتحوّل (transcode) على السيرفر، وبعدين
  `POST /reels/eligibility/` هو اللي بيقرر: لو الفيديو طولي 9:16 ومدته 90 ثانية
  أو أقل (حسب القياس بعد التحويل) يبقى **ريل**، ولو عرضي أو أطول يبقى
  **منشور فيديو**. اسم الملف عمره ما بيقرر ده. تلاوات إنستجرام بتروح على صفحة
  التلاوات.
- **ماركت بليس**: إعلانات من صور `Product/*` بأسعار منطقية بالجنيه، ومنيو البرجر
  والتشيكن من ملفات الـ `.xlsx` بأسعارها الحقيقية، وشوية موبايلات.
- **ستوريز** صور ونص لحوالي تلت الحسابات. الستوري بتنتهي بعد 24 ساعة، فلو عايز
  تجددها شغّل مرحلة `stories` تاني.
- **تفاعل**: ريأكشنز، كومنتات وردود، شير، حفظ، "مش مهتم"، مشاهدات ريلز، مشاهدات
  وحفظ إعلانات، ومشاهدات ستوري. المحتوى المشهور (رقم `1.2M views · 20K reactions`
  اللي في اسم الفيديو هو اللي بيحدد وزنه) بياخد تفاعل أكتر بكتير من الذيل الطويل،
  والحسابات النشيطة بتتفاعل أكتر. كده خوارزمية الترتيب يبقى عندها إشارة حقيقية
  تشتغل عليها.

### إيه اللي مش بيستخدمه أبدًا

- فولدر `Certificate`.
- أي سكرينشوت ممكن يبيّن بيانات خاصة أو أسرار: الإيميل والشات والبنك، محرر الكود
  (Visual Studio Code)، التيرمينال و`root@`، الـ DevTools، لوحة Dokploy، الـ Task
  Manager، صفحات الحسابات، والـ CV (حتى لو متحفوظ كصورة).
- ملفات PDF و`.ai` و`.psd` و`.rar` و`.ico`، وأي اسم شكله مستند شخصي.
- فيديوهات الموبايل الشخصية (`IMG_nnnn.MOV`) وتسجيل شاشة إعدادات ويندوز.
- لقطات الحرب الحية (فولدر `إران`)، وأي فيديو الكابشن بتاعه فيه عنف أو ضربات أو
  تحريض ضد شعوب أو أديان أو أشخاص بالاسم.
- الفيديوهات اللي أكبر من 200 ميجا، والصور الأصغر من 160 بكسل، والملفات المكررة.

وأي صورة تانية صالحة بتتنشر في مرحلة إضافية (`phase_extra_posts` جوه `posts`):
السكرينشوتات اللي على أول مستوى، و`MyFilter` و`WorkShop` و`Problime` و`Tools`
و`error` و`Pc Tester` و`Logo`، وفولدرات المشاريع `BackupData` و`login`
و`New folder`، والسكرينشوتات الطويلة بعد ما ناخد الجزء اللي فوق منها. مفاتيح
المرحلة دي جاية من الملفات نفسها، فمش بتغيّر أي حاجة اتعملت في المرحلة الأولى.

الصور بيتعاد حفظها JPEG من غير بيانات EXIF أو GPS، وبتتحفظ في `.seed-state/cache`.
الصور الشخصية اللي بيعملها السكريبت أشكال مجردة بألوان Tara، ومفيش صورة لوش شخص
حقيقي بتتحط على حساب وهمي.

### التشغيل

نفس الأوامر اللي في الجزء الإنجليزي فوق:

1. `--dry-run -v`: بيوريك الخطة من غير ما يكلم أي سيرفر.
2. تجربة صغيرة: `--accounts 8 --limit 2`.
3. التشغيل الكامل في الخلفية، وتسيب اللوج يتكتب في `.seed-state/run.log`.

لو التشغيل وقف في النص، شغّله تاني بنفس الأمر وهيكمّل من مكان ما وقف، حتى
الفيديوهات اللي كانت لسه بتتحوّل.

### الدخول بالحسابات

الإيميلات شكلها `seed.<handle>.<nnn>@example.com`، وكلها بنفس الباسورد
(الافتراضي `Seed-Tara-2026!`). الحسابات كلها متسجلة في `.seed-state/manifest.json`.

### حقوق المحتوى

الفيديوهات والصور حقوقها لأصحابها (قنوات أخبار، قرّاء، محلات). السكريبت ده
للاستخدام **المحلي** بس. السكريبت بيرفض يشتغل على أي سيرفر مش محلي إلا لو
استخدمت `--allow-remote`، وحتى ساعتها متستخدموش على سيرفر عام.

### عمره ما يشتغل على البرودكشن، والحسابات "اصطناعية"

السكريبت بيقفل قبل ما يعمل أي حاجة (حتى `--dry-run`) لو `TARA_ENV=production` أو لو
`--api` هو دومين البرودكشن (`DOMAIN` من البيئة أو من `.env_prod`، وبيقرا المفتاح ده بس).
وبعد مرحلة الحسابات بيسجّل كل حسابات الـ seed كحسابات اصطناعية في Tara Intelligence
(`intel_register_synthetic --label seed-dataset` في feed)، عشان نشاطها ما يختلطش
بالتحليلات الحقيقية. الـ ids بتتكتب كمان في `.seed-state/synthetic-accounts.json`، ولو
feed لسه ما فيهوش الأمر، سجّلهم بعدين بـ `--register-synthetic`.
