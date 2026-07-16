"""
滑块验证码自动识别与求解
双引擎: OpenCV (cv2) 优先，Pillow (PIL) 备选
模拟人类拖拽动作
"""
import asyncio
import io
import logging
import random
from typing import Optional

logger = logging.getLogger(__name__)

# 检测可用库
try:
    import cv2
    import numpy as np
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False

try:
    from PIL import Image, ImageFilter, ImageChops
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

if not HAS_CV2 and not HAS_PIL:
    logger.warning("captcha_solver: cv2 和 PIL 都未安装，滑块识别不可用")


class SliderCaptchaSolver:
    """滑块验证码求解器 (双引擎)"""

    def __init__(self, page):
        self.page = page

    async def solve(self, timeout_sec: int = 30) -> bool:
        """尝试解决滑块验证码"""
        if not HAS_CV2 and not HAS_PIL:
            return False

        try:
            # 1. 定位验证码区域
            slider_info = await self._find_slider_element()
            if not slider_info:
                return False

            # 2. 截图获取验证码图片
            bg_bytes, slider_bytes = await self._capture_captcha_images(slider_info)
            if bg_bytes is None:
                return False

            # 3. 计算缺口位置 (cv2 优先，PIL 备选)
            gap_x = 0
            if HAS_CV2:
                gap_x = self._find_gap_cv2(bg_bytes, slider_bytes)
            if gap_x <= 0 and HAS_PIL:
                gap_x = self._find_gap_pil(bg_bytes, slider_bytes)
            if gap_x <= 0:
                return False

            # 4. 获取滑块当前位置和拖拽轨道
            track_info = await self._get_track_geometry(slider_info)
            if not track_info:
                return False

            # 5. 计算实际拖拽距离
            drag_distance = gap_x * track_info["scale"]

            # 6. 模拟人类拖拽
            await self._human_like_drag(slider_info["handle"], drag_distance)

            # 7. 验证是否成功
            await asyncio.sleep(1.5)
            success = await self._verify_solved()

            if success:
                logger.info("CAPTCHA: 滑块验证自动通过")
            else:
                logger.warning("CAPTCHA: 滑块验证失败")

            return success

        except Exception as e:
            logger.warning(f"CAPTCHA solve error: {e}")
            return False

    async def _find_slider_element(self) -> Optional[dict]:
        """定位滑块验证码元素"""
        selectors = [
            {"panel": ".geetest_panel", "slider": ".geetest_slider_button"},
            {"panel": ".verify-slider", "slider": ".verify-slider-handle"},
            {"panel": "[class*='geetest']", "slider": "[class*='geetest_slider']"},
            {"panel": "[class*='captcha']", "slider": "[class*='slider']"},
        ]

        for sel in selectors:
            panel = await self.page.query_selector(sel["panel"])
            if panel:
                slider = await self.page.query_selector(sel["slider"])
                if slider:
                    return {"panel": panel, "handle": slider}
        return None

    async def _capture_captcha_images(self, slider_info: dict):
        """截图获取验证码背景图和滑块图"""
        try:
            panel_box = await slider_info["panel"].bounding_box()
            if not panel_box:
                return None, None

            bg_screenshot = await self.page.screenshot(
                clip={
                    "x": panel_box["x"],
                    "y": panel_box["y"],
                    "width": panel_box["width"],
                    "height": panel_box["height"],
                }
            )

            handle_box = await slider_info["handle"].bounding_box()
            slider_screenshot = None
            if handle_box:
                slider_screenshot = await self.page.screenshot(
                    clip={
                        "x": handle_box["x"],
                        "y": handle_box["y"],
                        "width": handle_box["width"],
                        "height": handle_box["height"],
                    }
                )

            return bg_screenshot, slider_screenshot

        except Exception as e:
            logger.debug(f"Capture error: {e}")
            return None, None

    # ── OpenCV 引擎 ──────────────────────────────────────

    def _find_gap_cv2(self, bg_bytes: bytes, slider_bytes: bytes = None) -> int:
        """OpenCV 找缺口"""
        try:
            bg_img = cv2.imdecode(np.frombuffer(bg_bytes, np.uint8), cv2.IMREAD_COLOR)
            if bg_img is None:
                return 0

            # 模板匹配
            if slider_bytes:
                slider_img = cv2.imdecode(np.frombuffer(slider_bytes, np.uint8), cv2.IMREAD_COLOR)
                if slider_img is not None:
                    result = cv2.matchTemplate(
                        cv2.cvtColor(bg_img, cv2.COLOR_BGR2GRAY),
                        cv2.cvtColor(slider_img, cv2.COLOR_BGR2GRAY),
                        cv2.TM_CCOEFF_NORMED
                    )
                    _, max_val, _, max_loc = cv2.minMaxLoc(result)
                    if max_val > 0.5:
                        return max_loc[0]

            # 边缘检测
            gray = cv2.cvtColor(bg_img, cv2.COLOR_BGR2GRAY)
            edges = cv2.Canny(gray, 50, 150)
            contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for contour in sorted(contours, key=cv2.contourArea, reverse=True):
                x, y, w, h = cv2.boundingRect(contour)
                if w > 20 and h > 20 and 0.3 < w / h < 3:
                    return x

            return 0
        except Exception:
            return 0

    # ── Pillow 引擎 (纯 Python，无原生依赖) ──────────────

    def _find_gap_pil(self, bg_bytes: bytes, slider_bytes: bytes = None) -> int:
        """Pillow 纯 Python 找缺口"""
        try:
            bg = Image.open(io.BytesIO(bg_bytes)).convert("L")
            width, height = bg.size

            if slider_bytes:
                # 模板匹配: 滑动窗口比较
                slider = Image.open(io.BytesIO(slider_bytes)).convert("L")
                sw, sh = slider.size
                best_x = 0
                best_score = float('inf')
                # 每隔5像素采样一次加速
                for x in range(0, width - sw, 5):
                    region = bg.crop((x, 0, x + sw, min(sh, height)))
                    diff = ImageChops.difference(region, slider.resize(region.size))
                    score = sum(diff.getdata())
                    if score < best_score:
                        best_score = score
                        best_x = x
                if best_score < sw * sh * 50:  # 阈值
                    return best_x

            # 像素方差法
            pixels = list(bg.getdata())
            window = 20
            min_var = float('inf')
            gap_x = 0
            for x in range(0, width - window, 3):
                col_values = [pixels[y * width + x + i] for y in range(height) for i in range(window)]
                mean = sum(col_values) / len(col_values)
                variance = sum((v - mean) ** 2 for v in col_values) / len(col_values)
                if variance < min_var:
                    min_var = variance
                    gap_x = x + window // 2

            if min_var < 300:
                return gap_x

            return 0
        except Exception:
            return 0

    # ── 拖拽模拟 ─────────────────────────────────────────

    async def _get_track_geometry(self, slider_info: dict) -> Optional[dict]:
        """获取拖拽轨道的几何信息"""
        try:
            panel_box = await slider_info["panel"].bounding_box()
            handle_box = await slider_info["handle"].bounding_box()
            if not panel_box or not handle_box:
                return None
            return {
                "track_width": panel_box["width"] - handle_box["width"],
                "handle_x": handle_box["x"],
                "panel_x": panel_box["x"],
                "scale": 1.0,
            }
        except Exception:
            return None

    async def _human_like_drag(self, handle, distance: float):
        """模拟人类拖拽动作（带加减速和抖动）"""
        try:
            box = await handle.bounding_box()
            if not box:
                return

            start_x = box["x"] + box["width"] / 2
            start_y = box["y"] + box["height"] / 2

            await self.page.mouse.move(start_x, start_y)
            await asyncio.sleep(random.uniform(0.05, 0.15))
            await self.page.mouse.down()
            await asyncio.sleep(random.uniform(0.05, 0.1))

            current_x = start_x
            total = 0.0

            # 加速阶段 (30%)
            accel_dist = distance * 0.3
            for i in range(6):
                step = accel_dist / 6 * (i + 1) / 6
                jitter_y = random.uniform(-2, 2)
                current_x += step
                total += step
                await self.page.mouse.move(current_x, start_y + jitter_y)
                await asyncio.sleep(random.uniform(0.01, 0.03))

            # 匀速阶段 (50%)
            mid_dist = distance * 0.5
            for i in range(10):
                step = mid_dist / 10
                jitter_y = random.uniform(-1, 1)
                current_x += step
                total += step
                await self.page.mouse.move(current_x, start_y + jitter_y)
                await asyncio.sleep(random.uniform(0.02, 0.04))

            # 减速阶段 (20%)
            remaining = distance - total
            for i in range(5):
                step = remaining / 5 * (1 - i / 8)
                jitter_y = random.uniform(-0.5, 0.5)
                current_x += step
                await self.page.mouse.move(current_x, start_y + jitter_y)
                await asyncio.sleep(random.uniform(0.03, 0.06))

            # 最终到位
            await self.page.mouse.move(start_x + distance, start_y + random.uniform(-0.5, 0.5))
            await asyncio.sleep(random.uniform(0.05, 0.1))
            await self.page.mouse.up()

        except Exception as e:
            logger.debug(f"Drag error: {e}")

    async def _verify_solved(self) -> bool:
        """验证是否通过验证码"""
        try:
            panel = await self.page.query_selector(
                ".geetest_panel, .verify-slider, [class*='captcha'], [class*='geetest']"
            )
            if not panel:
                return True
            success = await self.page.query_selector(
                ".geetest_success, .verify-success, [class*='success']"
            )
            if success:
                return True
            await asyncio.sleep(1)
            html = await self.page.content()
            if "验证通过" in html or "success" in html.lower():
                return True
            return False
        except Exception:
            return False


async def auto_solve_captcha(page, timeout_sec: int = 30) -> bool:
    """自动解决滑块验证码的入口函数"""
    if not HAS_CV2 and not HAS_PIL:
        logger.warning("cv2 和 PIL 都未安装，无法自动识别验证码")
        return False

    solver = SliderCaptchaSolver(page)
    return await solver.solve(timeout_sec)
