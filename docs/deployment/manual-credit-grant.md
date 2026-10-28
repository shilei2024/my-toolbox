# 手动给用户发放创作积分

适用场景：用户已登录但积分账户为空，或需要先赠送一些积分再体验 AI 生图。
生成服务使用本地 PostgreSQL（`ai.credit_accounts` / `ai.credit_ledger_entries`），
手动发放走受审计的 `admin_adjustment` 账目，不会绕过余额校验。

## 1. 找到用户 ID

```bash
sudo -u postgres psql -d mindfulpenpal -P pager=off -c \
  "SELECT id, email FROM public.users ORDER BY id;"
```

记下目标用户的 `id`。

## 2. 发放积分（把 `<USER_ID>` 换成真实 ID，`<AMOUNT>` 换成数量）

```bash
sudo -u postgres psql -d mindfulpenpal -v ON_ERROR_STOP=1 <<'SQL'
DO $$
DECLARE
  v_user_id integer := <USER_ID>;
  v_amount numeric := <AMOUNT>;
  v_available numeric;
  v_reserved numeric;
BEGIN
  INSERT INTO ai.credit_accounts (user_id) VALUES (v_user_id) ON CONFLICT DO NOTHING;
  UPDATE ai.credit_accounts
     SET available_amount = available_amount + v_amount,
         lifetime_granted = lifetime_granted + v_amount,
         version = version + 1
   WHERE user_id = v_user_id
   RETURNING available_amount, reserved_amount INTO v_available, v_reserved;
  INSERT INTO ai.credit_ledger_entries
    (user_id, entry_type, delta_available, available_after, reserved_after,
     source_type, source_ref, idempotency_key, metadata)
  VALUES
    (v_user_id, 'admin_adjustment', v_amount, v_available, v_reserved,
     'admin', 'manual:gallery', 'admin-adjustment:' || v_user_id || ':manual:gallery',
     '{"note":"manual grant"}');
END $$;
SQL
```

`idempotency_key` 固定，重复执行不会重复到账；如确需再次发放，请换一个 key。

## 3. 验证

```bash
sudo -u postgres psql -d mindfulpenpal -P pager=off -c "
SELECT u.email, c.available_amount, c.reserved_amount, c.lifetime_granted
FROM ai.credit_accounts c
JOIN public.users u ON u.id = c.user_id
ORDER BY c.created_at DESC;"
```

刷新 Gallery 的「积分与账单」页面即可看到余额。新用户默认的注册赠送（`BILLING_SIGNUP_GRANT`，默认 10）由生成服务在首次查询账单时自动发放，手动发放适用于存量账号或临时体验。
