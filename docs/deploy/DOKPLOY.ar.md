# تشغيل تارا على Dokploy: الخطوات بالترتيب

ده ملخص سريع ليك يا محمد. التفاصيل الكاملة في `docs/deploy/DOKPLOY.md`
(قسم **First deploy from zero**).

## قبل ما تبدأ

- سيرفر عليه Dokploy، وأقل حاجة **4 vCPU و12 جيجا رام** (الستاك حوالي 40 كونتينر).
- دومين: يا إما subdomain على `deplois.net`، يا إما دومين بتاعك على Cloudflare.

## 1. اعمل الـ Compose app

1. في Dokploy: **Create Project** وسمّيه `tara`، وبعدين **Create Service ← Compose**.
2. الـ Provider هو GitHub، والريبو `mohamedN2018/Tara`، والبرانش `feat/web-social-platform`
   (لما يتعمله merge غيّره لـ `main`).
3. الـ Compose path هو `./docker-compose.dokploy.yml`.
4. سيب **Isolated deployment** مقفول، لأن الملف نفسه بيدخل على `dokploy-network`.

## 2. ملف البيئة `.env_prod`

- الملف موجود جاهز عندك في الريبو المحلي (`.env_prod`)، وفيه كل الأسرار متولّدة جديدة
  وقوية. **ماتعملوش commit أبدًا**، وهو أصلًا متجاهَل في git.
- لو عايز تولّده من الأول: `./scripts/gen-dokploy-env.sh tara.yourdomain.com`.
  السكريبت مش هيكتب فوق ملف موجود إلا لو ضفت `--force`.
- افتح الملف واملأ البلوك اللي فوق خالص **`=== OWNER MUST FILL ===`**:
  - `DOMAIN`: الدومين بتاعك.
  - `EMAIL_HOST` و`EMAIL_HOST_USER` و`EMAIL_HOST_PASSWORD`: بيانات SMTP. لو لسه
    مفيش SMTP سيبهم فاضيين وخلي `EMAIL_VERIFICATION_REQUIRED=false`: الحساب الجديد
    بيتفعّل على طول ومفيش إيميلات بتتبعت. لما تضيف SMTP خليها `true`.
  - `DEFAULT_FROM_EMAIL`: لو سبته فاضي هيبقى `no-reply@DOMAIN`.
  - `LIVEKIT_NODE_IP`: الـ IP العام بتاع السيرفر (للمكالمات).
  - `LIVEKIT_TURN_DOMAIN`: لو بتستخدم Cloudflare (شوف خطوة 3).
  - S3 أو R2 وGoogle وTelegram اختياري، سيبهم فاضيين لو مش محتاجهم.
- انسخ الملف كله والزقه في Dokploy في تاب **Environment** ودوس **Save**.
- خلي نسخة منه في password manager، و**ماتولّدوش تاني بعد أول deploy**: الباسوردات
  الجديدة مش بتوصل للداتابيز القديمة، ومفتاح JWT جديد بيعمل logout لكل الناس.

## 3. الدومين وCloudflare

- **لو subdomain على deplois.net:** حط `DOMAIN=tara.deplois.net` وخلاص.
- **لو دومين بتاعك على Cloudflare:**
  1. اعمل `A` record باسم `tara` على IP السيرفر، وخليه **DNS only** (السحابة رمادي)،
     واعمل Deploy لحد ما شهادة Let's Encrypt تطلع.
  2. بعد كده حوّله **Proxied** (السحابة برتقاني) وخلي SSL/TLS على **Full (strict)**.
  3. Cloudflare مش بيعدّي UDP، فاعمل record تاني زي `turn` على نفس الـ IP وخليه
     **DNS only**، وحط `LIVEKIT_TURN_DOMAIN=turn.yourdomain.com` و`LIVEKIT_NODE_IP`.
  4. الخطة المجانية بتقفل الرفع عند 100 ميجا، فالفيديوهات الأكبر من كده هتفشل.
- **ماتضيفش حاجة في تاب Domains** في Dokploy، لأن الـ labels موجودة في الملف.

بعد كده دوس **Deploy**. أول build بياخد وقت. كل سيرفس بيعمل `migrate` لوحده
وهو بيقوم، فمفيش migrate job منفصل.

## 4. الباك أب

- اعرف اسم البروجكت اللي Dokploy مشغّله (مش هيبقى `tara`):
  ```bash
  P=$(docker ps --format '{{.Names}}' | sed -n 's/-identity-1$//p' | head -1); echo "$P"
  ```
- اعمل Schedule يومي في Dokploy (أو cron):
  ```bash
  COMPOSE_PROJECT=$P BACKUP_DIR=/var/backups/tara /etc/dokploy/compose/<app>/code/scripts/backup.sh
  ```
- انقل الباك أب برّه السيرفر، وخلي `.env_prod` معاه.
- للاسترجاع: `scripts/restore.sh <مجلد الباك أب>` على volumes فاضية.

## 5. المكالمات (LiveKit)

- افتح البورتات دي في الفايرول:
  ```bash
  ufw allow 7881/tcp && ufw allow 50000/udp && ufw allow 3478/udp
  ```
- لو مش عايز مكالمات: شيل `calls` من `COMPOSE_PROFILES` وفضّي `LIVEKIT_API_KEY`.

## 6. أول أدمن

سجّل حساب من الموقع وأكد الإيميل، وبعدين:
```bash
docker exec $P-identity-1 python manage.py create_admin you@example.com
```
اعمل logout وlogin تاني عشان الصلاحية تظهر.

## 7. اتأكد إن كله شغال

```bash
curl -fsS https://$DOMAIN/healthz.txt
curl -fsS https://$DOMAIN/.well-known/jwks.json
docker exec $P-feed-consumer-1 python -m tara_events.topology migrate   # مرة واحدة
docker exec $P-feed-consumer-1 python -m tara_events.topology status    # المفروض يطلع 0
```
وبعدين من المتصفح: سجّل حساب، ارفع صورة، ابعت رسالة، وافتح **Admin ← Health**
وشوف إن كل السيرفسات `ready`.

في أول تشغيل الأمر الوحيد اللي محتاجه هو `topology migrate` مرة واحدة (بيحط الـ policies
عشان `status` يطلع 0). أوامر زي `backfill_search` و`backfill_message_seq` بتتشغل بس وانت
بتعمل upgrade من نسخة قديمة.

## 8. التحديث والرجوع

- **التحديث:** اقرا ملاحظات الـ upgrade في `DOKPLOY.md`، وضيف أي متغيرات جديدة
  في Environment الأول، واعمل backup، وبعدين push ثم Deploy.
- **متغيرات اتضافت في fix round 3 (رسائل دعم تارا):** لو الـ `.env_prod` بتاعك
  اتولّد قبلها ضيفهم في Environment **قبل** الـ Deploy، لأن الـ stack مش هيقوم من غير
  `CHAT_IDENTITY_SECRET`:

  | المتغير | القيمة |
  |---|---|
  | `CHAT_IDENTITY_SECRET` | إجباري على identity وchat: `openssl rand -hex 32`، ويكون مختلف عن `INTERNAL_JWT_SECRET` و`ADMIN_IDENTITY_SECRET`. chat وidentity بس اللي بيستخدموه. |
  | `CHAT_NOTIFY_SUPPORT_TEAM` | اختياري على chat، الافتراضي `true`: كل رسالة لدعم تارا بتوصل إشعار `message.support` لفريق الدعم (اللي معاه `moderation.case.view`) ويفتح `/admin/support?conversation=<id>`. |

  الترتيب: انشر notification-consumer وidentity الأول (أو مع chat). لو chat سبقهم
  الإشعار بس هو اللي بيضيع، والرسالة نفسها محفوظة وعدّاد صندوق الدعم بيحسبها. مفيش
  migrations ولا أوامر تتشغل مرة واحدة. التفاصيل في `DOKPLOY.md`
  (*Upgrading: support team notices*). أما `EMAIL_VERIFICATION_REQUIRED` فمشروح
  فوق في خطوة 2.
- **الرجوع:** ارجع لـ commit قبله واعمل Deploy. الـ migrations كلها إضافية فالنسخة
  القديمة بتشتغل عادي. **ماترجعش migrations لورا**، ولو محتاج الداتا ترجع
  استرجع الباك أب.

## 9. إعادة الـ Deploy بالـ webhook

ممكن Dokploy يعمل Deploy لوحده مع كل push بدل ما تدوس **Deploy** بإيدك. هو بيشغّل نفس
الأمر بتاع الزرار (`up -d --build --remove-orphans`)، وبيقرا المتغيرات من تاب
Environment، فالـ volumes ومفاتيح JWT بتفضل زي ما هي.

1. لو الـ Provider هو GitHub: شغّل **Autodeploy** في الـ compose service، والـ GitHub App
   بتاعة Dokploy هتعمل Deploy مع كل push على البرانش المتحدد.
2. غير كده: خد الـ Dokploy webhook URL من تاب **Deployments** في السيرفس، وفي GitHub افتح
   الريبو ← **Settings ← Webhooks ← Add webhook**، وحطه في Payload URL، وخلي الـ content
   type `application/json`، واختار **Just the push event**. الـ push على أي برانش تاني
   بيتجاهل.
3. الـ Dokploy webhook URL جواه token، وأي حد معاه يقدر يعمل Deploy. خليه في password
   manager، و**ماتحطوش أبدًا في الريبو** ولا في issue ولا في شات. لو اتسرّب، اعمله
   regenerate من نفس التاب وحدّث الـ webhook في GitHub.

قبل أي release فيها متغيرات جديدة، ضيفها في Environment الأول (خطوة 8).

## 10. لو الـ Deploy فشل: "pull access denied" أو network reset

**الأعراض:** اللوج بيطلع سطر زي ده لكل image من `tara/*`:

```text
Error pull access denied for tara/feed, repository does not exist or may require 'docker login'
```

وفي الآخر بيقع بخطأ شبكة وهو بيسحب image زي `rabbitmq` من Docker Hub
(`connection reset by peer` أو `TLS handshake timeout`).

**السبب:** images تارا (`tara/*`) مش موجودة على Docker Hub، Dokploy بيبنيها على السيرفر.
الـ workers والـ consumers كانوا كاتبين `image: tara/<svc>` من غير `build`، فـ Compose كان
بيحاول يسحبها من Docker Hub الأول. Compose بيتجاهل الفشل ده لما سيرفس تانية بتبني نفس
الـ image، فالسطور دي كانت دوشة بس، لكن كل سطر منها طلب زيادة على Docker Hub. والـ Deploy
وقف فعلًا بسبب الـ network reset بتاع Docker Hub.

**اللي اتصلح في `docker-compose.dokploy.yml`:**

- الـ 15 سيرفس اللي ليهم `build` (14 باك إند + `web`) عليهم `pull_policy: build`، يعني
  بتتبني دايمًا ومش بتتسحب.
- الـ 24 سيرفس اللي بيستخدموا نفس الـ images (`*-worker` و`*-consumer` و`media-transcoder`
  و`realtime-bridge`) عليهم `pull_policy: never`. Compose بيبني كل الـ images قبل ما يعمل أي
  كونتينر، فبيقوموا من الـ image اللي اتبنت في نفس الـ `up -d --build`.
- الحاجات الوحيدة اللي بتتسحب هي الـ images الخارجية، وكلها متثبتة على tag أو digest محدد:
  `postgres:16.15-alpine` و`redis:7.4.11-alpine` و`rabbitmq:3.13.7-management-alpine`
  و`livekit/livekit-server:v1.13.10` وimages الـ `minio` والـ `minio-client` بتوع Chainguard.
  Mailpit للـ dev بس ومش موجود في الملف ده، والإيميل بيروح على SMTP اللي في `EMAIL_HOST`.

**تعمل إيه لو حصل:**

1. **الـ reset بتاع Docker Hub مؤقت.** دوس **Deploy** تاني أو اعمل push عشان الـ webhook
   يشتغل. الـ layers اللي نزلت بتفضل على السيرفر، فالمحاولة الجاية بتكمّل من مكانها.
2. **لو لسه شايف `pull access denied for tara/...`:** يبقى البرانش اللي عليه الـ Deploy مافيهوش
   التصليح ده. راجع البرانش والـ commit في لوج الـ Deploy.
3. **لو الـ reset بيتكرر:** اعمل registry mirror على السيرفر. مثلًا ضيف ده في
   `/etc/docker/daemon.json` واعمل restart لـ Docker:

   ```json
   { "registry-mirrors": ["https://mirror.gcr.io"] }
   ```

   الـ restart بيوقّف Dokploy وكل الكونتينرات شوية، فاعمله في وقت هادي. و`docker login` على
   السيرفر بيرفع حد Docker Hub عن الـ pulls من غير حساب.
4. **لو الخطأ `required variable ... is missing a value`:** يبقى تاب Environment مافيهوش
   `.env_prod` كامل. Dokploy بيكتب التاب في `.env`، والأمر مش بيقرا غيره. الزق الملف كله،
   ومعاه بلوك `OWNER MUST FILL` متملّي وكل متغير جديد في ملاحظات الـ release، ودوس **Save**
   واعمل Deploy تاني. **ماتولّدوش من جديد** لو الستاك شغال قبل كده (خطوة 2).

للتأكد على جهازك من غير ما تلمس السيرفر، استخدم env تجريبي (مش `.env_prod`) واعمل
`config -q` و`pull --ignore-buildable`؛ الأوامر في `DOKPLOY.md` (القسم 10). كل images تارا
هتطلع `Skipped`. استخدم `config -q` دايمًا، لأن `config` من غير `-q` بيطبع كل الأسرار.
