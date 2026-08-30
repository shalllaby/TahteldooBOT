import sys
import os
from openai import OpenAI

# Force UTF-8 stdout
sys.stdout.reconfigure(encoding='utf-8')

key = "8524054eb6424a4692eb2591522b1ce7.sD1orVkuyYPHlDY3"
base_url = "https://open.bigmodel.cn/api/paas/v4/"

print("🔍 جاري اختبار الاتصال بمزود Z.AI (GLM-4)...")

models_to_test = ["glm-4-flash", "glm-4", "GLM-4-Flash"]
success = False

for model_name in models_to_test:
    try:
        print(f"📡 فحص النموذج: {model_name}...")
        client = OpenAI(api_key=key, base_url=base_url)
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": "أنت محرر صحفي لجريدة تحت الضوء الإخبارية."},
                {"role": "user", "content": "اكتب خبر صحفي قصير جداً في سطرين عن الاكتشافات التكنولوجية."}
            ],
            max_tokens=150,
            temperature=0.7
        )
        content = response.choices[0].message.content
        print("\n✅ تم الاتصال بنجاح وتوليد الاستجابة:")
        print("--------------------------------------------------")
        print(content)
        print("--------------------------------------------------")
        success = True
        break
    except Exception as e:
        print(f"❌ تعذر الاتصال بالنموذج {model_name}: {e}")

if not success:
    print("\n⚠️ لم نتمكن من الوصول لنموذج GLM عبر المسار المباشر، جاري اختبار بيئة Z.AI البديلة...")
