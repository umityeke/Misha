import sys

from core.observation_privacy import protect_observation

def get_active_window_text(denylist=None) -> str:
    """
    Kullanıcının aktif olduğu (ön plandaki) macOS penceresindeki
    erişilebilirlik (Accessibility - AX) metinlerini hiyerarşik
    olarak çıkarır ve döndürür.
    Eğer yetki yoksa veya macOS değilse boş string döner.
    """
    if sys.platform != "darwin":
        return ""
        
    try:
        from AppKit import NSWorkspace
        import ApplicationServices
    except ImportError:
        # PyObjC kurulu değil
        return ""

    try:
        # 1. Aktif uygulamayı bul
        workspace = NSWorkspace.sharedWorkspace()
        active_app = workspace.frontmostApplication()
        if not active_app:
            return ""
            
        pid = active_app.processIdentifier()
        app_name = active_app.localizedName()
        if not protect_observation(app_name, "", "", denylist=denylist).allowed:
            return ""
        
        # 2. AXUIElement oluştur
        ax_app = ApplicationServices.AXUIElementCreateApplication(pid)
        
        # 3. Pencereleri al
        err, windows = ApplicationServices.AXUIElementCopyAttributeValue(ax_app, "AXWindows", None)
        if err != 0 or not windows:
            return f"[{app_name}] (Erişilebilirlik verisi okunamadı veya pencere yok)"
            
        output = [f"Aktif Uygulama: {app_name}\n"]
        
        def traverse_element(element, depth=0, max_depth=12):
            if depth > max_depth:
                return
                
            indent = "  " * depth
            
            # Rol (Role)
            err_role, role = ApplicationServices.AXUIElementCopyAttributeValue(element, "AXRole", None)
            
            # Başlık (Title)
            err_title, title = ApplicationServices.AXUIElementCopyAttributeValue(element, "AXTitle", None)
            
            # Değer (Value)
            err_val, val = ApplicationServices.AXUIElementCopyAttributeValue(element, "AXValue", None)
            
            # Description (Description)
            err_desc, desc = ApplicationServices.AXUIElementCopyAttributeValue(element, "AXDescription", None)
            
            line_parts = []
            if err_role == 0 and role:
                line_parts.append(f"[{role}]")
            if err_title == 0 and title and isinstance(title, str) and title.strip():
                line_parts.append(f"Title: '{title.strip()}'")
            if err_val == 0 and val and isinstance(val, str) and val.strip():
                line_parts.append(f"Value: '{val.strip()}'")
            elif err_desc == 0 and desc and isinstance(desc, str) and desc.strip():
                line_parts.append(f"Desc: '{desc.strip()}'")
                
            if line_parts:
                out_str = f"{indent}- {' '.join(line_parts)}"
                if len(out_str) > 300:
                    out_str = out_str[:297] + "..."
                
                # Sadece anlamsız grup kalabalıklarını basmamak için:
                if len(line_parts) > 1 or role not in ("AXGroup", "AXUnknown", "AXWindow", "AXScrollArea"):
                    output.append(out_str)
                
            # Alt elemanlar (Children)
            err_child, children = ApplicationServices.AXUIElementCopyAttributeValue(element, "AXChildren", None)
            if err_child == 0 and children:
                # Limit children to prevent massive hangs
                for child in children[:100]:
                    traverse_element(child, depth + 1, max_depth)
                    
        # İlk pencere genellikle aktif olan ana penceredir
        main_window = windows[0]
        err_title, w_title = ApplicationServices.AXUIElementCopyAttributeValue(main_window, "AXTitle", None)
        w_title_str = w_title if (err_title == 0 and w_title) else "İsimsiz Pencere"
        if not protect_observation(
            app_name, w_title_str, "", denylist=denylist
        ).allowed:
            return ""
        output.append(f"Aktif Pencere: {w_title_str}")
        
        traverse_element(main_window, depth=0, max_depth=12)
        
        final_text = "\n".join(output)
        protected = protect_observation(
            app_name, w_title_str, final_text, denylist=denylist
        )
        return protected.text if protected.allowed else ""
        
    except Exception as e:
        print(f"[macOS Observe] AX okuma hatası: {e}")
        return ""

if __name__ == "__main__":
    print("Test: macOS Accessibility Reader")
    print("-" * 40)
    print(get_active_window_text())
