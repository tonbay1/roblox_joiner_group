import time
import os
import json
import traceback
from DrissionPage import ChromiumOptions, Chromium
from tqdm import tqdm

# ฟังก์ชันสำหรับเข้าร่วมกลุ่มหลังจากล็อกอินด้วยคุกกี้
def join_groups(tab, account_index, username):
    print(f"[บัญชี {account_index + 1}] กำลังเข้าร่วมกลุ่ม...")
    joined_groups = []
    
    try:
        # อ่านลิงก์กลุ่มจากไฟล์
        with open("group_links.txt", "r") as f:
            group_links = [line.strip() for line in f.readlines() if line.strip()]
        
        if not group_links:
            print(f"[บัญชี {account_index + 1}] ไม่พบลิงก์กลุ่มในไฟล์ group_links.txt")
            return joined_groups
        
        # เข้าร่วมแต่ละกลุ่ม
        for group_link in group_links:
            try:
                # เปิดลิงก์กลุ่ม
                print(f"[บัญชี {account_index + 1}] กำลังเปิดลิงก์กลุ่ม: {group_link}")
                tab.get(group_link)
                # ลดเวลารอลงเหลือ 1 วินาที
                time.sleep(1)
                
                # ดึงชื่อกลุ่ม
                group_name = tab.run_js('return document.querySelector("h1") ? document.querySelector("h1").innerText : "Unknown Group"')
                
                # ตรวจสอบว่าเป็นสมาชิกแล้วหรือไม่
                is_member = tab.run_js('''
                    return document.body.innerText.includes("You are a member") || 
                           document.querySelector('button[data-testid="group-leave-button"]') !== null ||
                           Array.from(document.querySelectorAll('button')).some(btn => btn.textContent.includes('Leave'));
                ''')
                
                if is_member:
                    print(f"[บัญชี {account_index + 1}] คุณเป็นสมาชิกของกลุ่ม '{group_name}' อยู่แล้ว")
                    joined_groups.append({"name": group_name, "link": group_link, "status": "already_member"})
                    continue
                
                # คลิกปุ่ม Join Group
                join_clicked = tab.run_js('''
                    const joinButtons = Array.from(document.querySelectorAll('button')).filter(btn => 
                        btn.textContent.includes('Join') && 
                        !btn.textContent.includes('Leave')
                    );
                    
                    if (joinButtons.length > 0) {
                        joinButtons[0].click();
                        return true;
                    }
                    return false;
                ''')
                
                if join_clicked:
                    print(f"[บัญชี {account_index + 1}] คลิกปุ่ม Join Group สำหรับกลุ่ม '{group_name}'")
                    
                    # เพิ่มเวลารอเป็น 3 วินาที เพื่อให้แคปช่าโหลด (ถ้ามี)
                    time.sleep(3)
                    
                    # ตรวจจับ captcha แบบละเอียดขึ้น
                    captcha_js_result = tab.run_js('''
                        // ตรวจสอบเฉพาะ iframe ที่มองเห็นและ src มี funcaptcha/captcha/arkose
                        const iframes = Array.from(document.querySelectorAll('iframe')).filter(f =>
                            f.offsetParent !== null && (
                                (f.src && (f.src.includes('funcaptcha') || f.src.includes('arkose') || f.src.includes('captcha')))
                            )
                        );
                        // ตรวจสอบ element ที่มองเห็นและมี class captcha-container
                        const captchaDiv = document.querySelector('.captcha-container');
                        let visibleCaptchaDiv = false;
                        let debugCaptchaDiv = {};
                        if (captchaDiv) {
                            const style = window.getComputedStyle(captchaDiv);
                            const rect = captchaDiv.getBoundingClientRect();
                            visibleCaptchaDiv =
                                style.display !== 'none' &&
                                style.visibility !== 'hidden' &&
                                rect.width > 10 && rect.height > 10 &&  // ปรับ threshold ตามความเหมาะสม
                                captchaDiv.offsetParent !== null;
                            debugCaptchaDiv = {
                                display: style.display,
                                visibility: style.visibility,
                                width: rect.width,
                                height: rect.height,
                                offsetParent: captchaDiv.offsetParent !== null
                            };
                        }
                        return {
                            iframeCount: iframes.length,
                            visibleCaptchaDiv,
                            debugCaptchaDiv,
                            detected: iframes.length > 0 || visibleCaptchaDiv
                        };
                    ''')
                    print(f"[DEBUG] captcha_js_result: {captcha_js_result}")
                    captcha_detected = captcha_js_result['detected']
                    if captcha_detected:
                        print(f"[บัญชี {account_index + 1}] พบ captcha รอให้ solver ทำงาน...")
                        wait_for_captcha_solver(tab, print_prefix=f"[บัญชี {account_index + 1}] ")
                    else:
                        print(f"[บัญชี {account_index + 1}] ไม่พบ captcha")
                    # รอและตรวจสอบสถานะการเข้าร่วมกลุ่ม (สูงสุด 30 วินาที)
                    joined = False
                    sidebar_groups = []
                    for i in range(1):  # 6 รอบ ๆ ละ 5 วินาที
                        # 1. ตรวจสอบรายชื่อกลุ่มใน sidebar
                        sidebar_groups = tab.run_js('''
                            return Array.from(document.querySelectorAll('div[role="menu"] a, .group-list a')).map(a => a.innerText.trim());
                        ''')
                        if group_name in sidebar_groups:
                            print(f"[บัญชี {account_index + 1}] ✅ เข้าร่วมกลุ่ม '{group_name}' สำเร็จ (พบใน sidebar)")
                            print(f"รายชื่อกลุ่มใน sidebar: {sidebar_groups}")
                            joined_groups.append({"name": group_name, "link": group_link, "status": "success"})
                            joined = True
                            break
                        # 2. ตรวจสอบปุ่ม Join/Leave
                        join_leave_buttons = tab.run_js('''
                            return Array.from(document.querySelectorAll("button")).map(btn => btn.textContent);
                        ''')
                        if not any("Join" in btn or "Leave" in btn for btn in join_leave_buttons):
                            print(f"[บัญชี {account_index + 1}] ✅ เข้าร่วมกลุ่ม '{group_name}' สำเร็จ (ไม่มีปุ่ม Join/Leave)")
                            joined_groups.append({"name": group_name, "link": group_link, "status": "success"})
                            joined = True
                            break
                        print(f"[บัญชี {account_index + 1}] ⏳ รอการยืนยันเข้าร่วมกลุ่ม... (รอบที่ {i+1})")
                        time.sleep(5)
                    if not joined:
                        print(f"[บัญชี {account_index + 1}] ❌ ไม่พบการยืนยันเข้าร่วมกลุ่ม '{group_name}'")
                        print(f"รายชื่อกลุ่มใน sidebar: {sidebar_groups}")
                        joined_groups.append({"name": group_name, "link": group_link, "status": "failed"})
                else:
                    print(f"[บัญชี {account_index + 1}] ไม่สามารถคลิกปุ่ม Join Group สำหรับกลุ่ม '{group_name}'")
                    joined_groups.append({"name": group_name, "link": group_link, "status": "click_failed"})
            except Exception as e:
                print(f"[บัญชี {account_index + 1}] เกิดข้อผิดพลาดในการเข้าร่วมกลุ่ม: {e}")
                joined_groups.append({"name": group_name, "link": group_link, "status": "error", "error": str(e)})
        
        print(f"[บัญชี {account_index + 1}] เข้าร่วมกลุ่มเสร็จสิ้น")
        return joined_groups
    except Exception as e:
        print(f"[บัญชี {account_index + 1}] เกิดข้อผิดพลาดในการเข้าร่วมกลุ่ม: {e}")
        return joined_groups

# ฟังก์ชันสำหรับรอ solver แก้ captcha และแสดงสถานะ
# จะรอจนกว่า captcha จะหายไป หรือหมดเวลา (สูงสุด 60 วินาที)
def wait_for_captcha_solver(tab, print_prefix=""):
    max_wait = 60  # วินาที
    interval = 5
    waited = 0
    while waited < max_wait:
        # ตรวจสอบว่ายังมี captcha อยู่หรือไม่
        captcha_still = tab.run_js('''
            return document.querySelector('iframe[src*="funcaptcha"]') !== null || \
                   document.querySelector('iframe[src*="captcha"]') !== null ||\
                   document.querySelector('iframe[src*="arkose"]') !== null ||\
                   document.querySelector('.captcha-container') !== null ||\
                   document.body.innerHTML.includes('captcha') ||\
                   document.body.innerHTML.includes('Captcha') ||\
                   document.body.innerHTML.includes('verification');
        ''')
        if not captcha_still:
            print(f"{print_prefix}✅ แก้ captcha สำเร็จ!")
            return True
        print(f"{print_prefix}⏳ กำลังรอให้ solver แก้ captcha... (รอแล้ว {waited} วินาที)")
        time.sleep(interval)
        waited += interval
    print(f"{print_prefix}❌ หมดเวลารอ captcha ยังไม่ถูกแก้ไข")
    return False

# ฟังก์ชันสำหรับล็อกอินด้วยคุกกี้
def login_with_cookie(browser, cookie_value):
    try:
        # เปิดหน้าล็อกอิน
        tab = browser.new_tab("https://www.roblox.com")
        time.sleep(2)
        
        # ใช้วิธีการตั้งค่า cookies ที่ถูกต้องสำหรับ DrissionPage
        tab.run_js(f'''
            document.cookie = ".ROBLOSECURITY={cookie_value};domain=.roblox.com;path=/";
        ''')
        
        # รีโหลดหน้าเว็บเพื่อให้คุกกี้มีผล
        tab.refresh()
        time.sleep(2)
        
        # ตรวจสอบว่าล็อกอินสำเร็จหรือไม่
        is_logged_in = tab.run_js('''
            return document.querySelector('.nav-robux-amount') !== null || 
                   document.querySelector('.rbx-name-container') !== null ||
                   document.querySelector('.navbar-user') !== null ||
                   !document.querySelector('.login-button');
        ''')
        
        if is_logged_in:
            # ดึงชื่อผู้ใช้
            username = tab.run_js('''
                const nameElement = document.querySelector('.text-nav');
                return nameElement ? nameElement.innerText.trim() : "Unknown";
            ''')
            print(f"✅ ล็อกอินสำเร็จ: {username}")
            return tab, username
        else:
            print("❌ ล็อกอินไม่สำเร็จ คุกกี้อาจหมดอายุหรือไม่ถูกต้อง")
            return None, None
    except Exception as e:
        print(f"❌ เกิดข้อผิดพลาดในการล็อกอิน: {e}")
        traceback.print_exc()
        return None, None

# ฟังก์ชันหลัก
def main():
    print("Roblox Group Joiner - เครื่องมือเข้าร่วมกลุ่ม Roblox อัตโนมัติ")
    print("=" * 70)
    
    # ตรวจสอบไฟล์ group_links.txt
    if not os.path.exists("group_links.txt"):
        print("สร้างไฟล์ group_links.txt สำหรับใส่ลิงก์กลุ่มที่ต้องการเข้าร่วม...")
        with open("group_links.txt", "w") as f:
            f.write("https://www.roblox.com/groups/5502618/Hapless-Studios#!/about\n")
            f.write("# เพิ่มลิงก์กลุ่มที่ต้องการเข้าร่วมในแต่ละบรรทัด\n")
    
    # ตรวจสอบไฟล์ cookies.txt
    if not os.path.exists("cookies.txt"):
        print("สร้างไฟล์ cookies.txt สำหรับใส่คุกกี้ .ROBLOSECURITY...")
        with open("cookies.txt", "w") as f:
            f.write("# ใส่คุกกี้ .ROBLOSECURITY ในแต่ละบรรทัด (ไม่ต้องใส่ชื่อคุกกี้)\n")
            f.write("# ตัวอย่าง: _|WARNING:-DO-NOT-SHARE-THIS...\n")
    
    # อ่านคุกกี้จากไฟล์
    try:
        with open("cookies.txt", "r") as f:
            cookies = [line.strip() for line in f.readlines() if line.strip() and not line.startswith("#")]
        
        if not cookies:
            print("❌ ไม่พบคุกกี้ในไฟล์ cookies.txt กรุณาเพิ่มคุกกี้ก่อนรันโปรแกรมอีกครั้ง")
            return
        
        print(f"📋 พบคุกกี้ทั้งหมด {len(cookies)} รายการ")
    except Exception as e:
        print(f"❌ เกิดข้อผิดพลาดในการอ่านไฟล์ cookies.txt: {e}")
        return
    
    # ตั้งค่า ChromiumOptions
    co = ChromiumOptions()
    co.set_argument("--disable-blink-features=AutomationControlled")
    co.set_argument("--disable-web-security")
    co.set_argument("--no-sandbox")
    # --- เพิ่มการโหลด extension OMOCAPTCHA ---
    omo_extension_path = r"ใส่ที่อยู่ส่วนขยาย"
    if os.path.exists(omo_extension_path):
        co.add_extension(omo_extension_path)
        print(f"✅ โหลดส่วนขยาย OMOCAPTCHA: {omo_extension_path}")
    else:
        print(f"⚠️ ไม่พบส่วนขยาย OMOCAPTCHA ที่ {omo_extension_path}")
    
    # เปิดเบราว์เซอร์
    try:
        print("🌐 กำลังเปิดเบราว์เซอร์...")
        browser = Chromium(addr_or_opts=co)
    except Exception as e:
        print(f"❌ เกิดข้อผิดพลาดในการเปิดเบราว์เซอร์: {e}")
        return
    
    # ล็อกอินและเข้าร่วมกลุ่มสำหรับแต่ละคุกกี้
    for i, cookie in enumerate(cookies):
        print(f"\n[บัญชี {i+1}/{len(cookies)}] กำลังล็อกอิน...")
        tab, username = login_with_cookie(browser, cookie)
        
        if tab and username:
            # เข้าร่วมกลุ่ม
            join_groups(tab, i, username)
        
        print(f"[บัญชี {i+1}/{len(cookies)}] เสร็จสิ้น")
        
        # ถ้ายังไม่ใช่บัญชีสุดท้าย ให้รอ 10 วินาทีก่อนเริ่มบัญชีถัดไป
        if i < len(cookies) - 1:
            print(f"กำลังรอ 10 วินาทีก่อนเริ่มบัญชีถัดไป...")
            for j in range(10, 0, -1):
                print(f"เริ่มบัญชีถัดไปในอีก {j} วินาที...", end="\r")
                time.sleep(1)
            print(" " * 50, end="\r")  # ล้างข้อความนับถอยหลัง
    
    print("\n✅ การทำงานเสร็จสิ้น")
    input("กดปุ่ม Enter เพื่อปิดโปรแกรม...")

if __name__ == "__main__":
    main()
