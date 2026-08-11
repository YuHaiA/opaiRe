from pathlib import Path

ms_path = Path(r"C:\Users\yu\Desktop\opaiRe\utils\email_providers\mail_service.py")
ms = ms_path.read_text(encoding="utf-8")

new_wait = '''            elif mode == "openai_cpa":
                # Fast path for openai_cpa: background listener + short polling.
                # Total wait capped at 8-10s instead of 100s.
                if getattr(cfg, 'OPENAI_CPA_WEBHOOK_SECRET', "") or getattr(cfg, 'OPENAI_CPA_BRIDGE_ENABLED', False) or getattr(cfg, 'OPENAI_CPA_LOCAL_WEBHOOK', False):
                    target_email = email.lower().strip()
                    bridge_stopper = None
                    wait_started = time.time()
                    total_timeout = 8.0
                    try:
                        try:
                            from utils.email_bridge.client import ensure_listen, stop_listen
                            bridge_stopper = stop_listen
                            ensure_listen(target_email, ttl_sec=total_timeout + 20.0)
                        except Exception:
                            bridge_stopper = None

                        from utils.auth_core import code_pool
                        for _ in range(5):  # max 5 short polls
                            current_code = _consume_code_pool_code(
                                target_email,
                                ignore_code=ignore_code,
                                allow_relay_fallback=True,
                            )
                            if current_code:
                                waited = time.time() - wait_started
                                print(
                                    f"[{cfg.ts()}] [SUCCESS] 项目专属邮箱 OPENAI-CPA ({mask_email(target_email)}) "
                                    f"提取成功: {current_code}，等待 {waited:.1f}s"
                                )
                                return current_code

                            time.sleep(1.6)  # 1.6s per poll for ~8s total

                        waited = time.time() - wait_started
                        print(
                            f"[{cfg.ts()}] [ERROR] 超时未获取到不同于 {ignore_code} 的新验证码 "
                            f"({mask_email(target_email)}，已等 {waited:.1f}s，8s内轮询)"
                        )
                        return ""
                    except ImportError:
                        print(f"[{cfg.ts()}] [ERROR] 无法导入内存池！")
                    finally:
                        if bridge_stopper is not None:
                            try:
                                bridge_stopper(target_email)
                            except Exception:
                                pass
'''

old = '''            elif mode == "openai_cpa":
                # Keep upstream polling cadence (sleep 2s). Bridge is additive:
                # background HTTP/WS listener + per-loop HTTP/sqlite fallback.
                if getattr(cfg, 'OPENAI_CPA_WEBHOOK_SECRET', "") or getattr(cfg, 'OPENAI_CPA_BRIDGE_ENABLED', False) or getattr(cfg, 'OPENAI_CPA_LOCAL_WEBHOOK', False):
                    target_email = email.lower().strip()
                    bridge_stopper = None
                    wait_started = time.time()
                    try:
                        try:
                            from utils.email_bridge.client import ensure_listen, stop_listen
                            bridge_stopper = stop_listen
                            # TTL covers upstream-style wait window: attempts * 2s (+ cushion)
                            ensure_listen(target_email, ttl_sec=max(60, int(max_attempts) * 3 + 15))
                        except Exception:
                            bridge_stopper = None

                        from utils.auth_core import code_pool  # noqa: F401  ensure module import side effects
                        for attempt in range(max_attempts):
                            current_code = _consume_code_pool_code(
                                target_email,
                                ignore_code=ignore_code,
                                allow_relay_fallback=True,
                            )
                            if current_code:
                                waited = time.time() - wait_started
                                print(
                                    f"[{cfg.ts()}] [SUCCESS] 项目专属邮箱 OPENAI-CPA ({mask_email(target_email)}) "
                                    f"提取成功: {current_code}，等待 {waited:.1f}s"
                                )
                                return current_code

                            # Upstream-compatible idle between polls.
                            time.sleep(2)

                        waited = time.time() - wait_started
                        print(
                            f"[{cfg.ts()}] [ERROR] 超时未获取到不同于 {ignore_code} 的新验证码 "
                            f"({mask_email(target_email)}，已等 {waited:.1f}s)"
                        )
                        return ""
                    except ImportError:
                        print(f"[{cfg.ts()}] [ERROR] 无法导入内存池！")
                    finally:
                        if bridge_stopper is not None:
                            try:
                                bridge_stopper(target_email)
                            except Exception:
                                pass
'''

if old not in ms:
    raise SystemExit('old wait block missing')
ms = ms.replace(old, new_wait, 1)
ms_path.write_text(ms, encoding='utf-8')
compile(ms, str(ms_path), 'exec')
print('mail_service wait path optimized to 8s')
