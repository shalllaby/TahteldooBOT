; ===================================================
; Inno Setup Script
; جريدة تحت الضوء الإخبارية — v3.0
; نظام نشر الأخبار الذكي
; ===================================================

#define MyAppName "جريدة تحت الضوء الإخبارية"
#define MyAppVersion "3.0"
#define MyAppPublisher "جريدة تحت الضوء"
#define MyAppURL "https://www.tahteldoo.com/"
#define MyAppExeName "TahtElDooPublisher.exe"
#define MyAppDir "TahtElDooPublisher"

[Setup]
; معلومات التطبيق
AppId={{A9F2B3C4-D5E6-7890-ABCD-EF1234567890}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} v{#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}

; مسار التثبيت الافتراضي
DefaultDirName={autopf}\{#MyAppDir}
DefaultGroupName={#MyAppName}
AllowNoIcons=no

; ملف الإخراج
OutputDir=..\dist
OutputBaseFilename=TahtElDooPublisher_Setup_v3.0
SetupIconFile=..\ico.ico

; ضغط عالي
Compression=lzma2/ultra64
SolidCompression=yes
LZMAUseSeparateProcess=yes

; واجهة المثبّت
WizardStyle=modern
WizardResizable=no
WizardSizePercent=100

; إعدادات أخرى
ShowLanguageDialog=no
PrivilegesRequiredOverridesAllowed=dialog
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName} v{#MyAppVersion}

; لغة مناسبة للعربية
RightToLeft=no

[Languages]
Name: "arabic"; MessagesFile: "compiler:Default.isl"; LanguageName: "العربية"

[CustomMessages]
arabic.WelcomeLabel1=مرحباً بك في برنامج تثبيت%n{#MyAppName}
arabic.WelcomeLabel2=سيقوم هذا الإعداد بتثبيت [name/ver] على جهازك.%n%nيُنصح بإغلاق جميع التطبيقات الأخرى قبل الاستمرار.%n%nاضغط التالي للمتابعة، أو إلغاء للخروج.
arabic.FinishedHeadingLabel=اكتمل تثبيت [name]
arabic.FinishedLabelNoIcons=تم تثبيت [name] بنجاح على جهازك.
arabic.FinishedLabel=تم تثبيت [name] بنجاح. يمكنك تشغيل البرنامج من خلال الأيقونات المُنشأة.
arabic.ClickFinish=اضغط إنهاء لإغلاق هذا الإعداد.

[Tasks]
Name: "desktopicon"; Description: "إنشاء أيقونة على سطح المكتب"; GroupDescription: "أيقونات إضافية:"; Flags: checked
Name: "startupicon"; Description: "تشغيل البرنامج تلقائياً مع بدء Windows"; GroupDescription: "إعدادات التشغيل:"; Flags: unchecked

[Files]
; ملفات التطبيق الرئيسية
Source: "..\dist\TahtElDooPublisher\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; قائمة ابدأ
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\ico.ico"
Name: "{group}\إلغاء تثبيت {#MyAppName}"; Filename: "{uninstallexe}"

; سطح المكتب
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\ico.ico"; Tasks: desktopicon

[Registry]
; تشغيل مع Windows (اختياري)
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "{#MyAppName}"; ValueData: """{app}\{#MyAppExeName}"""; Flags: uninsdeletevalue; Tasks: startupicon

[Run]
; تشغيل البرنامج بعد التثبيت
Filename: "{app}\{#MyAppExeName}"; Description: "تشغيل {#MyAppName} الآن"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; تنظيف الملفات المؤقتة عند الحذف
Type: filesandordirs; Name: "{app}\__pycache__"
Type: filesandordirs; Name: "{app}\logs"

[Code]
// رسالة ترحيب مخصصة
procedure InitializeWizard;
begin
  WizardForm.WelcomeLabel1.Font.Size := 14;
  WizardForm.WelcomeLabel1.Font.Style := [fsBold];
end;

// التحقق من وجود نسخة قديمة
function InitializeSetup(): Boolean;
begin
  Result := True;
end;
