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
  - `EMAIL_HOST` و`EMAIL_HOST_USER` و`EMAIL_HOST_PASSWORD`: بيانات SMTP. من غيرها
    الستاك مش هيقوم، لأن كل حساب جديد لازم يأكد الإيميل.
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
- **الرجوع:** ارجع لـ commit قبله واعمل Deploy. الـ migrations كلها إضافية فالنسخة
  القديمة بتشتغل عادي. **ماترجعش migrations لورا**، ولو محتاج الداتا ترجع
  استرجع الباك أب.
