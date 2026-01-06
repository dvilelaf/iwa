# ANALYSIS.md - Comprehensive Code Improvement Plan

> **IMPORTANTE**: Este documento contiene el plan de mejoras detallado. NO implementar hasta revisión.
>
> **Fecha**: 2026-01-06
> **Analista**: Senior Engineer
> **Objetivo**: Mejorar arquitectura, seguridad y código limpio

---

## Índice

1. [Resumen Ejecutivo](#resumen-ejecutivo)
2. [Clasificación de Prioridades](#clasificación-de-prioridades)
3. [Análisis por Archivo](#análisis-por-archivo)
   - [Core](#core)
   - [Contracts](#contracts)
   - [Services](#services)
   - [Plugins](#plugins)
   - [Web](#web)
   - [TUI](#tui)
   - [Tools](#tools)

---

## Resumen Ejecutivo

| Categoría | Archivos | Issues Críticos | Issues Medios | Issues Bajos |
|-----------|----------|-----------------|---------------|--------------|
| Core | 15 | 3 | 12 | 8 |
| Services | 6 | 2 | 5 | 4 |
| Contracts | 4 | 0 | 3 | 2 |
| Plugins | 12 | 4 | 8 | 6 |
| Web | 15 | 2 | 7 | 5 |
| TUI | 6 | 0 | 3 | 4 |
| Tools | 4 | 0 | 2 | 3 |

---

## Clasificación de Prioridades

- **CRÍTICO (P0)**: Vulnerabilidad de seguridad o pérdida potencial de fondos
- **ALTO (P1)**: Bug potencial o violación arquitectónica grave
- **MEDIO (P2)**: Mejora de mantenibilidad o código limpio
- **BAJO (P3)**: Optimización o mejora menor

---

## Buenas Prácticas Ya Implementadas

> El codebase tiene una base sólida de seguridad. Estas prácticas están correctamente implementadas:

### Criptografía (`keys.py`, `mnemonic.py`)

| Práctica | Implementación |
|----------|----------------|
| **KDF** | Scrypt (n=2^14, r=8, p=1) - recomendado por OWASP |
| **Cifrado** | AES-256-GCM con autenticación |
| **Aleatoridad** | `os.urandom()` para datos criptográficos |
| **Permisos de archivo** | `os.chmod(0o600)` en wallet.json |
| **Mnemónico** | BIP-39 con 24 palabras (máxima entropía) |
| **Derivación HD** | BIP-44 con paths estándar |
| **Aislamiento de tests** | Bloquea uso de wallet real en tests |
| **Backups** | Auto-backup con timestamp antes de guardar |

### Autenticación Web (`dependencies.py`, `server.py`)

| Práctica | Implementación |
|----------|----------------|
| **Timing-safe** | `secrets.compare_digest()` para comparar passwords |
| **HTTP 401** | Respuesta con header WWW-Authenticate |
| **Bearer + API Key** | Soporta ambos métodos de auth |
| **Security Headers** | X-Frame-Options, X-XSS-Protection, Referrer-Policy |
| **CSP** | Content-Security-Policy configurado |
| **HSTS** | Opcional via `ENABLE_HSTS` env var |
| **Rate Limiting** | slowapi en endpoints críticos (/send, /eoa, /safe) |
| **CORS** | Configurable via `ALLOWED_ORIGINS` |

### Transacciones (`transaction.py`)

| Práctica | Implementación |
|----------|----------------|
| **Retry logic** | 3 intentos con backoff exponencial |
| **Gas handling** | Auto-incremento de gas 1.5x en fallos |
| **RPC rotation** | Rotación a RPC backup en errores de conexión |
| **Tx logging** | Todas las transacciones logueadas en DB |
| **Sin exposición** | Usa `key_storage.sign_transaction()` interno |

---

## Análisis por Archivo

---

### CORE

---

#### `src/iwa/core/chain.py` (947 líneas)

**ARQUITECTURA SÓLIDA**

| ID | Prioridad | Problema | Solución Propuesta |
|----|-----------|----------|-------------------|
| CHAIN-A1 | P2 | Archivo muy largo (947 líneas) | Dividir en módulos: `chain_interface.py`, `rate_limiter.py`, `rpc_manager.py` |
| CHAIN-A2 | P2 | `ChainInterfaces` es singleton global | Considerar inyección de dependencias para testing |
| CHAIN-A3 | P3 | Múltiples clases de cadenas (`Gnosis`, `Ethereum`) duplican código | Extraer clase base `SupportedChain` con configuración declarativa |

**SEGURIDAD**

| ID | Prioridad | Problema | Solución Propuesta |
|----|-----------|----------|-------------------|
| CHAIN-S1 | P1 | RPC URLs pueden contener API keys en logs | Sanitizar URLs antes de logging: `logger.info(f"Connecting to {sanitize_rpc_url(url)}")` |
| CHAIN-S2 | P2 | `TenderlyQuotaExceededError` expone detalles internos | Mensaje genérico para usuarios, detalles solo en logs |

**CÓDIGO LIMPIO**

| ID | Prioridad | Problema | Solución Propuesta |
|----|-----------|----------|-------------------|
| CHAIN-C1 | P2 | `get_token_decimals` tiene lógica compleja anidada | Extraer a métodos: `_get_decimals_from_cache()`, `_get_decimals_from_rpc()`, `_get_native_decimals()` |
| CHAIN-C2 | P3 | Magic numbers: `DEFAULT_RPC_TIMEOUT = 10` | Mover a `constants.py` |
| CHAIN-C3 | P2 | `ChainInterface.__init__` tiene >50 líneas | Extraer inicialización a métodos privados |

---

#### `src/iwa/core/keys.py` (341 líneas)

**ARQUITECTURA SÓLIDA**

| ID | Prioridad | Problema | Solución Propuesta |
|----|-----------|----------|-------------------|
| KEYS-A1 | P3 | `EncryptedAccount` y `KeyStorage` en mismo archivo | Separar en `encrypted_account.py` y `key_storage.py` |

**SEGURIDAD**

| ID | Prioridad | Problema | Solución Propuesta |
|----|-----------|----------|-------------------|
| KEYS-S1 | P2 | `_password` almacenado como `str` en memoria | Usar `pydantic.SecretStr` para limitar exposición accidental |
| KEYS-S2 | P3 | Sin mecanismo de rotación de claves | Documentar proceso manual o implementar `rotate_master_key()` |
| KEYS-S3 | P1 | Scrypt n=2^14 puede ser bajo para ataques modernos | Considerar aumentar a n=2^17 o usar Argon2id |
| KEYS-S4 | P0 | `get_signer()` devuelve `LocalAccount` con clave privada accesible | Documentar claramente que solo debe usarse para APIs que requieren signer (CowSwap). Considerar wrapper que no exponga `.key` |

**CÓDIGO LIMPIO**

| ID | Prioridad | Problema | Solución Propuesta |
|----|-----------|----------|-------------------|
| KEYS-C1 | P2 | `__init__` tiene lógica de protección de tests inline | Extraer a método `_validate_path_for_tests()` |
| KEYS-C2 | P3 | Comentario `# ... (create_safe omitted for brevity...)` en línea 295 | Eliminar comentario obsoleto |

---

#### `src/iwa/core/mnemonic.py` (384 líneas)

**ARQUITECTURA SÓLIDA**

| ID | Prioridad | Problema | Solución Propuesta |
|----|-----------|----------|-------------------|
| MNEM-A1 | P2 | `EncryptedMnemonic`, `MnemonicStorage`, `MnemonicManager` en mismo archivo | Mantener juntos (cohesión alta) pero considerar subdirectorio `crypto/` |

**SEGURIDAD**

| ID | Prioridad | Problema | Solución Propuesta |
|----|-----------|----------|-------------------|
| MNEM-S1 | P1 | `MnemonicStorage.save()` no aplica `os.chmod(0o600)` | Añadir después de `json.dump()`: `os.chmod(file_path, 0o600)` |
| MNEM-S2 | P2 | `derive_eth_accounts_from_mnemonic` devuelve `private_key_hex` | Considerar devolver solo direcciones; claves solo bajo demanda |
| MNEM-S3 | P3 | `del priv_bytes, acct, priv_hex` no garantiza limpieza (gc) | Usar `ctypes.memset` para limpiar memoria sensible |

**CÓDIGO LIMPIO**

| ID | Prioridad | Problema | Solución Propuesta |
|----|-----------|----------|-------------------|
| MNEM-C1 | P3 | Typo: `cypher` debería ser `cipher` | Corregir en `EncryptedMnemonic` (L44) |
| MNEM-C2 | P2 | Constantes duplicadas entre `EncryptedMnemonic.encrypt()` y `MnemonicManager.encrypt_mnemonic()` | Reutilizar las constantes globales |

---

#### `src/iwa/core/db.py` (224 líneas)

**ARQUITECTURA SÓLIDA**

| ID | Prioridad | Problema | Solución Propuesta |
|----|-----------|----------|-------------------|
| DB-A1 | P2 | `log_transaction` tiene demasiados parámetros (14) | Crear `TransactionLogData` dataclass |
| DB-A2 | P3 | Lógica de merge de tags/extra_data en `log_transaction` | Extraer a métodos: `_merge_tags()`, `_merge_extra_data()` |

**SEGURIDAD**

| ID | Prioridad | Problema | Solución Propuesta |
|----|-----------|----------|-------------------|
| DB-S1 | P2 | Base de datos sin encriptación at-rest | Documentar riesgo o implementar SQLCipher |
| DB-S2 | P3 | `synchronous = 0` puede perder datos en crash | Cambiar a `synchronous = 1` (NORMAL) para datos financieros |

**CÓDIGO LIMPIO**

| ID | Prioridad | Problema | Solución Propuesta |
|----|-----------|----------|-------------------|
| DB-C1 | P1 | Usa `print()` en vez de `logger` en migraciones y errores | Reemplazar todos los `print()` con `logger.error()` o `logger.warning()` |
| DB-C2 | P2 | `run_migrations` tiene `# noqa: C901` - complejidad alta | Refactorizar en funciones individuales por migración |
| DB-C3 | P2 | `log_transaction` tiene `# noqa: D103, C901` | Añadir docstring y reducir complejidad |

---

#### `src/iwa/core/wallet.py` (381 líneas)

**ARQUITECTURA SÓLIDA**

| ID | Prioridad | Problema | Solución Propuesta |
|----|-----------|----------|-------------------|
| WALLET-A1 | P3 | `Wallet` es facade que delega a servicios | Buena arquitectura - mantener |
| WALLET-A2 | P2 | `swap()` es método async pero otros son sync | Considerar hacer todos async o documentar claramente |

**SEGURIDAD**

| ID | Prioridad | Problema | Solución Propuesta |
|----|-----------|----------|-------------------|
| WALLET-S1 | P2 | `get_accounts_balances` usa `ThreadPoolExecutor` sin límite | Limitar max_workers para evitar DoS |

**CÓDIGO LIMPIO**

| ID | Prioridad | Problema | Solución Propuesta |
|----|-----------|----------|-------------------|
| WALLET-C1 | P3 | Docstrings incompletos en algunos métodos | Completar con Args, Returns, Raises |

---

### SERVICES

---

#### `src/iwa/core/services/transfer.py` (1357 líneas)

**ARQUITECTURA SÓLIDA**

| ID | Prioridad | Problema | Solución Propuesta |
|----|-----------|----------|-------------------|
| TRANS-A1 | P1 | Archivo demasiado largo (1357 líneas) | Dividir: `transfer_native.py`, `transfer_erc20.py`, `multi_send.py`, `swap.py`, `drain.py` |
| TRANS-A2 | P2 | `multi_send` tiene `# noqa: C901` | Refactorizar extrayendo helpers |

**SEGURIDAD**

| ID | Prioridad | Problema | Solución Propuesta |
|----|-----------|----------|-------------------|
| TRANS-S1 | P0 | Whitelist validation es bypass-able si `config.core` es None | Añadir check: `if not config.core: return False` (fail-closed) |
| TRANS-S2 | P1 | `_is_supported_token` permite cualquier dirección 0x | Requerir token estar en whitelist explícita |

**CÓDIGO LIMPIO**

| ID | Prioridad | Problema | Solución Propuesta |
|----|-----------|----------|-------------------|
| TRANS-C1 | P2 | Métodos `_send_*_via_*` tienen código duplicado | Extraer logging y db calls a método común |
| TRANS-C2 | P3 | Import `TYPE_CHECKING` pero algunos tipos no son string literals | Consistencia en type hints |

---

#### `src/iwa/core/services/transaction.py` (166 líneas)

**ARQUITECTURA SÓLIDA**

| ID | Prioridad | Problema | Solución Propuesta |
|----|-----------|----------|-------------------|
| TXN-A1 | P3 | Bien estructurado | Mantener |

**SEGURIDAD**

| ID | Prioridad | Problema | Solución Propuesta |
|----|-----------|----------|-------------------|
| TXN-S1 | P3 | `max_retries = 3` hardcoded | Hacer configurable vía settings |

**CÓDIGO LIMPIO**

| ID | Prioridad | Problema | Solución Propuesta |
|----|-----------|----------|-------------------|
| TXN-C1 | P2 | `sign_and_send` tiene `# noqa: C901` | Extraer: `_prepare_transaction()`, `_execute_with_retry()`, `_log_success()` |

---

### CONTRACTS

---

#### `src/iwa/core/contracts/erc20.py` (80 líneas)

**ARQUITECTURA SÓLIDA**

| ID | Prioridad | Problema | Solución Propuesta |
|----|-----------|----------|-------------------|
| ERC20-A1 | P3 | Bien estructurado, hereda de `ContractInstance` | Mantener |

**SEGURIDAD**

| ID | Prioridad | Problema | Solución Propuesta |
|----|-----------|----------|-------------------|
| ERC20-S1 | P2 | `__init__` hace llamadas RPC sin manejo de errores | Envolver en try/except para contratos inválidos |
| ERC20-S2 | P3 | No valida que `decimals()` devuelva valor razonable (0-18) | Añadir validation: `if not 0 <= self.decimals <= 18: raise ValueError` |

**CÓDIGO LIMPIO**

| ID | Prioridad | Problema | Solución Propuesta |
|----|-----------|----------|-------------------|
| ERC20-C1 | P3 | Docstrings muy cortos ("Transfer.", "Approve.") | Expandir con descripción de parámetros |

---

### WEB

---

#### `src/iwa/web/server.py` (147 líneas)

**ARQUITECTURA SÓLIDA**

| ID | Prioridad | Problema | Solución Propuesta |
|----|-----------|----------|-------------------|
| SRV-A1 | P3 | Bien estructurado con middleware y routers | Mantener |

**SEGURIDAD**

| ID | Prioridad | Problema | Solución Propuesta |
|----|-----------|----------|-------------------|
| SRV-S1 | P2 | CSP tiene `'unsafe-inline'` para scripts y styles | Refactorizar JS/CSS para eliminar inline; usar nonces |
| SRV-S2 | P3 | Rate limiter en memoria se pierde al reiniciar | Considerar Redis para persistencia en producción |
| SRV-S3 | P2 | `allow_headers=["*"]` es muy permisivo | Especificar headers permitidos explícitamente |

**CÓDIGO LIMPIO**

| ID | Prioridad | Problema | Solución Propuesta |
|----|-----------|----------|-------------------|
| SRV-C1 | P3 | `global_exception_handler` podría loggear stack trace en producción | Añadir flag para control de detalle en logs |

---

#### `src/iwa/web/dependencies.py` (77 líneas)

**ARQUITECTURA SÓLIDA**

| ID | Prioridad | Problema | Solución Propuesta |
|----|-----------|----------|-------------------|
| DEP-A1 | P2 | `wallet = Wallet()` singleton global en import | Usar lazy initialization o dependency injection |

**SEGURIDAD**

| ID | Prioridad | Problema | Solución Propuesta |
|----|-----------|----------|-------------------|
| DEP-S1 | P3 | Sin rate limiting en endpoint de auth | Añadir `@limiter.limit("5/minute")` a `verify_auth` |

**CÓDIGO LIMPIO**

| ID | Prioridad | Problema | Solución Propuesta |
|----|-----------|----------|-------------------|
| DEP-C1 | P3 | Import circular evitado con lazy import | Documentar por qué es necesario |

---

### PLUGINS

---

#### `src/iwa/plugins/olas/service_manager.py`

**ARQUITECTURA SÓLIDA**

| ID | Prioridad | Problema | Solución Propuesta |
|----|-----------|----------|-------------------|
| SM-A1 | P0 | Archivo extremadamente largo (2000+ líneas) | Dividir en: `service_lifecycle.py`, `staking_manager.py`, `drain_manager.py`, `checkpoint_manager.py` |
| SM-A2 | P1 | Muchos métodos tienen `# noqa: C901` | Plan de refactorización urgente |

**SEGURIDAD**

| ID | Prioridad | Problema | Solución Propuesta |
|----|-----------|----------|-------------------|
| SM-S1 | P1 | Operaciones de staking sin confirmación doble | Añadir confirmación para operaciones irreversibles |
| SM-S2 | P2 | Logs pueden contener direcciones sensibles | Revisar nivel de logging para operaciones críticas |

**CÓDIGO LIMPIO**

| ID | Prioridad | Problema | Solución Propuesta |
|----|-----------|----------|-------------------|
| SM-C1 | P1 | Métodos con >100 líneas | Máximo 30 líneas por método |
| SM-C2 | P2 | Nesting excesivo (>4 niveles) | Usar early returns y guard clauses |

---

## Próximos Pasos

1. **Revisión**: Este documento debe ser revisado por el equipo antes de implementación
2. **Priorización**: Atacar P0 y P1 primero
3. **Testing**: Cada cambio debe incluir tests
4. **Incrementalidad**: Implementar en PRs pequeños y atómicos

---

## Archivos Analizados (Continuación)

---

### CONTRACTS (Continuación)

---

#### `src/iwa/core/contracts/contract.py` (298 líneas)

**ARQUITECTURA SÓLIDA**

| ID | Prioridad | Problema | Solución Propuesta |
|----|-----------|----------|-------------------|
| CONTR-A1 | P3 | Bien estructurado como clase base | Mantener |

**SEGURIDAD**

| ID | Prioridad | Problema | Solución Propuesta |
|----|-----------|----------|-------------------|
| CONTR-S1 | P2 | `decode_error` puede exponer detalles internos | Añadir flag para sanitizar mensajes en producción |

**CÓDIGO LIMPIO**

| ID | Prioridad | Problema | Solución Propuesta |
|----|-----------|----------|-------------------|
| CONTR-C1 | P3 | PANIC_CODES como dict global | Mover a clase o constants.py |

**Especificación**: Crear método `decode_error(self, error_data: str, sanitize: bool = False)` que omita detalles técnicos cuando `sanitize=True`.

---

#### `src/iwa/core/contracts/multisend.py` (72 líneas)

✅ **LIMPIO** - Sin issues significativos. Archivo pequeño y bien estructurado.

---

### CORE (Continuación)

---

#### `src/iwa/core/models.py` (345 líneas)

**ARQUITECTURA SÓLIDA**

| ID | Prioridad | Problema | Solución Propuesta |
|----|-----------|----------|-------------------|
| MOD-A1 | P2 | `Config` usa singleton implícito con `model_post_init` | Documentar comportamiento singleton claramente |

**SEGURIDAD**

| ID | Prioridad | Problema | Solución Propuesta |
|----|-----------|----------|-------------------|
| MOD-S1 | P3 | `StorableModel.save_*` no aplica permisos restrictivos | Añadir `os.chmod(path, 0o600)` después de save para archivos sensibles |

**CÓDIGO LIMPIO**

| ID | Prioridad | Problema | Solución Propuesta |
|----|-----------|----------|-------------------|
| MOD-C1 | P3 | Múltiples modelos en un archivo | Considerar separar en `config.py`, `storable.py`, `token.py` |

**Especificación**: En `StorableModel.save()`, después de escribir el archivo:
```python
if sensitive:
    os.chmod(path, 0o600)
```
Añadir parámetro `sensitive: bool = False` a los métodos save.

---

#### `src/iwa/core/monitor.py` (197 líneas)

**ARQUITECTURA SÓLIDA**

| ID | Prioridad | Problema | Solución Propuesta |
|----|-----------|----------|-------------------|
| MON-A1 | P3 | Bien estructurado | Mantener |

**SEGURIDAD**

| ID | Prioridad | Problema | Solución Propuesta |
|----|-----------|----------|-------------------|
| MON-S1 | P3 | Logs pueden exponer direcciones monitoreadas | Considerar flag para modo silencioso |

**CÓDIGO LIMPIO**

| ID | Prioridad | Problema | Solución Propuesta |
|----|-----------|----------|-------------------|
| MON-C1 | P1 | `check_activity` tiene `# noqa: C901` (134 líneas) | Dividir en: `_check_native_transfers()`, `_check_erc20_transfers()`, `_process_logs()` |
| MON-C2 | P3 | Comentario inline `# ... inside check_activity ...` | Eliminar comentarios de desarrollo |

**Especificación para MON-C1**:
```python
def check_activity(self):
    """Check for new blocks and logs."""
    if not self._should_check():
        return

    from_block, to_block = self._get_block_range()
    found_txs = []
    found_txs.extend(self._check_native_transfers(from_block, to_block))
    found_txs.extend(self._check_erc20_transfers(from_block, to_block))

    self.last_checked_block = to_block
    if found_txs:
        self.callback(found_txs)
```

---

#### `src/iwa/core/pricing.py` (92 líneas)

✅ **LIMPIO** - Archivo pequeño, bien estructurado, con caché y retry logic.

---

#### `src/iwa/core/settings.py` (96 líneas)

**ARQUITECTURA SÓLIDA**

| ID | Prioridad | Problema | Solución Propuesta |
|----|-----------|----------|-------------------|
| SET-A1 | P3 | Singleton con `@singleton` decorator | Buena práctica - mantener |

**SEGURIDAD**

| ID | Prioridad | Problema | Solución Propuesta |
|----|-----------|----------|-------------------|
| SET-S1 | P3 | `SecretStr` usado correctamente para claves | ✅ Correcto |

**CÓDIGO LIMPIO**

| ID | Prioridad | Problema | Solución Propuesta |
|----|-----------|----------|-------------------|
| SET-C1 | P3 | `load_tenderly_profile_credentials` es largo | Considerar extraer a método helper |

---

### SERVICES (Continuación)

---

#### `src/iwa/core/services/account.py` (58 líneas)

✅ **LIMPIO** - Servicio pequeño, bien estructurado.

---

#### `src/iwa/core/services/balance.py` (114 líneas)

✅ **LIMPIO** - Servicio con retry logic bien implementado.

---

#### `src/iwa/core/services/safe.py` (332 líneas)

**ARQUITECTURA SÓLIDA**

| ID | Prioridad | Problema | Solución Propuesta |
|----|-----------|----------|-------------------|
| SAFE-A1 | P3 | Bien estructurado | Mantener |

**SEGURIDAD**

| ID | Prioridad | Problema | Solución Propuesta |
|----|-----------|----------|-------------------|
| SAFE-S1 | P2 | `_get_signer_keys` devuelve claves privadas raw | Documentar que es solo uso interno; añadir `# SECURITY: Internal only` |
| SAFE-S2 | P1 | Claves en memoria durante `_sign_and_execute_safe_tx` | Limpiar variables explícitamente después de uso: `signer_keys.clear()` |

**CÓDIGO LIMPIO**

| ID | Prioridad | Problema | Solución Propuesta |
|----|-----------|----------|-------------------|
| SAFE-C1 | P1 | `create_safe` tiene `# noqa: C901` (150 líneas) | Dividir en: `_prepare_safe_deployment()`, `_execute_deployment()`, `_save_safe_to_wallet()` |

**Especificación para SAFE-C1**:
```python
def create_safe(self, deployer_tag, owner_tags, threshold, chain_name, tag=None, salt_nonce=None):
    """Deploy a new Safe."""
    # Step 1: Validate and prepare
    deployer, owners, chain = self._prepare_safe_deployment(
        deployer_tag, owner_tags, chain_name
    )

    # Step 2: Execute deployment
    safe_address, tx_hash = self._execute_deployment(
        deployer, owners, threshold, chain, salt_nonce
    )

    # Step 3: Save to wallet
    self._save_safe_to_wallet(safe_address, owners, threshold, chain_name, tag)

    return safe_address
```

---

### PLUGINS

---

#### `src/iwa/plugins/gnosis/cow.py` (538 líneas)

**ARQUITECTURA SÓLIDA**

| ID | Prioridad | Problema | Solución Propuesta |
|----|-----------|----------|-------------------|
| COW-A1 | P1 | Archivo largo (538 líneas) | Dividir en: `cow_swap.py`, `cow_orders.py`, `cow_quotes.py` |
| COW-A2 | P2 | Lazy loading de cowdao_cowpy con globals | Refactorizar a import condicional o factory |

**SEGURIDAD**

| ID | Prioridad | Problema | Solución Propuesta |
|----|-----------|----------|-------------------|
| COW-S1 | P1 | `__init__` acepta `private_key_or_signer` como string | Preferir siempre `LocalAccount`, nunca strings con claves |
| COW-S2 | P2 | Slippage hardcoded a 0.5% | Hacer configurable por usuario |

**CÓDIGO LIMPIO**

| ID | Prioridad | Problema | Solución Propuesta |
|----|-----------|----------|-------------------|
| COW-C1 | P3 | `warnings.filterwarnings` al inicio de archivo | Mover a función de init o conftest |
| COW-C2 | P2 | Globals `swap_tokens = None` como placeholders | Usar import lazy con `importlib` |

**Especificación para COW-S1**:
```python
def __init__(self, signer: LocalAccount, chain: SupportedChain):
    """Initialize CowSwap.

    Args:
        signer: LocalAccount object (NEVER pass raw private key string)
        chain: Supported chain configuration
    """
    if isinstance(signer, str):
        raise TypeError("Pass LocalAccount, not private key string")
    self.signer = signer
    self.chain = chain
```

---

#### `src/iwa/plugins/olas/plugin.py` (253 líneas)

**ARQUITECTURA SÓLIDA**

| ID | Prioridad | Problema | Solución Propuesta |
|----|-----------|----------|-------------------|
| OLAS-A1 | P3 | Bien estructurado como Plugin | Mantener |

**SEGURIDAD**

| ID | Prioridad | Problema | Solución Propuesta |
|----|-----------|----------|-------------------|
| OLAS-S1 | P2 | `import_services` acepta password por CLI | Advertir sobre riesgos de pasar passwords en CLI |

**CÓDIGO LIMPIO**

| ID | Prioridad | Problema | Solución Propuesta |
|----|-----------|----------|-------------------|
| OLAS-C1 | P2 | `import_services` es largo (170 líneas) | Extraer: `_discover_services()`, `_import_keys()`, `_validate_import()` |

---

#### `src/iwa/plugins/olas/service_manager/` (Package)

**ARQUITECTURA SÓLIDA**

| ID | Prioridad | Problema | Solución Propuesta | Estado |
|----|-----------|----------|-------------------|--------|
| SM-A1 | P0 | **CRÍTICO**: Archivo extremadamente largo | Dividir en módulos (Mixins) | ✅ **RESUELTO** |
| SM-A2 | P1 | Muchos métodos con `# noqa: C901` | Cada método largo debe refactorizarse |

**SEGURIDAD**

| ID | Prioridad | Problema | Solución Propuesta |
|----|-----------|----------|-------------------|
| SM-S1 | P1 | Operaciones de staking irreversibles sin confirmación | Añadir parámetro `confirm: bool = True` y logging detallado |
| SM-S2 | P2 | Approval amounts pueden ser muy altos | Limitar approvals al mínimo necesario + 10% margen |

**CÓDIGO LIMPIO**

| ID | Prioridad | Problema | Solución Propuesta |
|----|-----------|----------|-------------------|
| SM-C1 | P0 | Métodos con >100 líneas | Máximo 30 líneas por método |
| SM-C2 | P1 | Nesting >4 niveles en `stake()`, `spin_up()` | Usar early returns y guard clauses |

**Especificación para SM-A1** (división del archivo):

```
src/iwa/plugins/olas/
├── service_manager/
│   ├── __init__.py          # Re-export ServiceManager
│   ├── base.py              # ServiceManager clase base
│   ├── lifecycle.py         # create, spin_up, wind_down
│   ├── staking.py           # stake, unstake, checkpoint
│   ├── drain.py             # drain_service, claim_rewards
│   └── validation.py        # _validate_*, helpers
```

---

### WEB ROUTERS

---

#### `src/iwa/web/routers/olas.py` (975 líneas)

**ARQUITECTURA SÓLIDA**

| ID | Prioridad | Problema | Solución Propuesta |
|----|-----------|----------|-------------------|
| OLAS-R-A1 | P0 | **CRÍTICO**: Archivo muy largo (975 líneas) | Dividir en: `olas_services.py`, `olas_staking.py`, `olas_admin.py` |
| OLAS-R-A2 | P2 | `get_staking_contracts` tiene función interna de 32 líneas | Extraer a método independiente |

**SEGURIDAD**

| ID | Prioridad | Problema | Solución Propuesta |
|----|-----------|----------|-------------------|
| OLAS-R-S1 | P2 | Endpoints críticos sin rate limiting | Añadir `@limiter.limit()` a stake, terminate, drain |
| OLAS-R-S2 | P3 | Excepciones exponen detalles internos | Sanitizar mensajes de error |

**CÓDIGO LIMPIO**

| ID | Prioridad | Problema | Solución Propuesta |
|----|-----------|----------|-------------------|
| OLAS-R-C1 | P1 | `get_staking_contracts` tiene `# noqa: C901` | Refactorizar complejidad |
| OLAS-R-C2 | P2 | Código duplicado en manejo de errores | Crear decorator `@handle_service_errors` |

**Especificación para OLAS-R-C2**:
```python
def handle_service_errors(func):
    """Decorator to standardize error handling in olas endpoints."""
    @wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except ServiceNotFoundError as e:
            raise HTTPException(404, f"Service not found: {e}")
        except StakingError as e:
            raise HTTPException(400, f"Staking error: {e}")
        except Exception as e:
            logger.exception(f"Unexpected error in {func.__name__}")
            raise HTTPException(500, "Internal error")
    return wrapper
```

---

#### `src/iwa/web/routers/swap.py` (309 líneas)

**ARQUITECTURA SÓLIDA**

| ID | Prioridad | Problema | Solución Propuesta |
|----|-----------|----------|-------------------|
| SWAP-A1 | P3 | Bien estructurado | Mantener |

**SEGURIDAD**

| ID | Prioridad | Problema | Solución Propuesta |
|----|-----------|----------|-------------------|
| SWAP-S1 | P2 | Sin rate limiting en `/swap` | Añadir `@limiter.limit("10/minute")` |
| SWAP-S2 | P3 | Validadores no verifican longitud máxima | Añadir `max_length` a Field() |

**CÓDIGO LIMPIO**

| ID | Prioridad | Problema | Solución Propuesta |
|----|-----------|----------|-------------------|
| SWAP-C1 | P3 | `run_async_quote` definida inline dos veces | Extraer a función helper |

---

#### `src/iwa/web/routers/transactions.py` (154 líneas)

✅ **LIMPIO** - Bien estructurado, tiene rate limiting, validación correcta.

---

#### `src/iwa/web/routers/accounts.py` (190 líneas)

**ARQUITECTURA SÓLIDA**

| ID | Prioridad | Problema | Solución Propuesta |
|----|-----------|----------|-------------------|
| ACC-A1 | P3 | Comentario `# --- Models (Temporary)` | Mover modelos a `web/models.py` |

**SEGURIDAD**

| ID | Prioridad | Problema | Solución Propuesta |
|----|-----------|----------|-------------------|
| ACC-S1 | P3 | Rate limiting adecuado | ✅ Correcto |

**CÓDIGO LIMPIO**

| ID | Prioridad | Problema | Solución Propuesta |
|----|-----------|----------|-------------------|
| ACC-C1 | P3 | `create_safe` usa `import time` dentro de función | Mover import al inicio |

---

## Resumen de Issues por Prioridad

### P0 (CRÍTICO) - 5 issues
1. **KEYS-S4**: `get_signer()` expone claves
2. **TRANS-S1**: Whitelist bypass si config.core es None
3. ~~**SM-A1**: service_manager.py tiene 2000+ líneas~~ (Resuelto)
4. **SM-C1**: Métodos con >100 líneas
5. **OLAS-R-A1**: olas.py router tiene 975 líneas

### P1 (ALTO) - 15 issues
1. **CHAIN-S1**: RPC URLs con API keys en logs
2. **KEYS-S3**: Scrypt n=2^14 puede ser bajo
3. **MNEM-S1**: MnemonicStorage.save() sin permisos
4. **DB-C1**: Usa print() en vez de logger
5. **TRANS-A1**: transfer.py tiene 1357 líneas
6. **TRANS-S2**: _is_supported_token permite cualquier 0x
7. **TXN-C1**: sign_and_send tiene C901
8. **MON-C1**: check_activity tiene C901
9. **SAFE-S2**: Claves en memoria sin limpiar
10. **SAFE-C1**: create_safe tiene C901
11. **COW-A1**: cow.py tiene 538 líneas
12. **COW-S1**: Acepta private key como string
13. **SM-A2**: Muchos métodos con C901
14. **SM-S1**: Operaciones irreversibles sin confirm
15. **OLAS-R-C1**: get_staking_contracts tiene C901

### P2 (MEDIO) - 25+ issues
(Ver tablas detalladas arriba)

### P3 (BAJO) - 20+ issues
(Ver tablas detalladas arriba)

---

## Plan de Implementación Sugerido

### Sprint 1: Seguridad Crítica (P0/P1 Security)
1. Fix whitelist bypass en transfer.py
2. Documentar uso de get_signer()
3. Añadir limpieza de claves en memoria
4. Sanitizar RPC URLs en logs

### Sprint 2: Refactorización Arquitectónica
1. Dividir service_manager.py en módulos
2. Dividir transfer.py
3. Dividir olas.py router
4. Dividir cow.py

### Sprint 3: Código Limpio
1. Eliminar todos los C901
2. Reemplazar print() con logger
3. Reducir métodos a <30 líneas
4. Mejorar docstrings

### Sprint 4: Mejoras Menores
1. Mover constantes a constants.py
2. Separar modelos en archivos
3. Añadir rate limiting faltante
4. Mejorar validaciones

---

## Archivos Adicionales Analizados

---

### CORE (Adicionales)

---

#### `src/iwa/core/cli.py` (212 líneas)

✅ **LIMPIO** - CLI bien estructurado con Typer. Plugin loading al final es correcto.

| ID | Prioridad | Problema | Solución Propuesta |
|----|-----------|----------|-------------------|
| CLI-C1 | P3 | Comentario duplicado `# Load Plugins` (líneas 193, 194) | Eliminar duplicado |

---

#### `src/iwa/core/plugins.py` (46 líneas)

✅ **LIMPIO** - ABC bien definida para plugins. Archivo pequeño.

---

#### `src/iwa/core/tables.py` (61 líneas)

✅ **LIMPIO** - Función simple de visualización con Rich.

---

#### `src/iwa/core/types.py` (60 líneas)

✅ **LIMPIO** - `EthereumAddress` bien implementado con validación y Pydantic schema.

---

#### `src/iwa/core/utils.py` (60 líneas)

✅ **LIMPIO** - Funciones helper correctamente implementadas.

---

### PLUGINS (Adicionales)

---

#### `src/iwa/plugins/gnosis/plugin.py` (69 líneas)

✅ **LIMPIO** - Plugin pequeño y bien estructurado.

---

#### `src/iwa/plugins/olas/contracts/staking.py` (404 líneas)

**ARQUITECTURA SÓLIDA**

| ID | Prioridad | Problema | Solución Propuesta |
|----|-----------|----------|-------------------|
| STAKE-A1 | P2 | Archivo largo con muchos métodos | Considerar dividir en `staking_read.py` (queries) y `staking_write.py` (transactions) |

**SEGURIDAD**

| ID | Prioridad | Problema | Solución Propuesta |
|----|-----------|----------|-------------------|
| STAKE-S1 | P3 | Documentación excelente sobre mecánicas de staking | ✅ Buena práctica |

**CÓDIGO LIMPIO**

| ID | Prioridad | Problema | Solución Propuesta |
|----|-----------|----------|-------------------|
| STAKE-C1 | P3 | `get_service_info` tiene muchos try/except anidados | Considerar extraer manejo de errores |

---

### TUI

---

#### `src/iwa/tui/app.py` (193 líneas)

**ARQUITECTURA SÓLIDA**

| ID | Prioridad | Problema | Solución Propuesta |
|----|-----------|----------|-------------------|
| TUI-A1 | P3 | Bien estructurado | Mantener |

**CÓDIGO LIMPIO**

| ID | Prioridad | Problema | Solución Propuesta |
|----|-----------|----------|-------------------|
| TUI-C1 | P2 | `trace()` función de debug escribe a archivo | Eliminar o usar logger |
| TUI-C2 | P3 | CSS inline en clase | Considerar mover a archivo `.css` separado |

---

### WEB (Adicionales)

---

#### `src/iwa/web/routers/state.py` (66 líneas)

✅ **LIMPIO** - Router pequeño, bien estructurado, con `_obscure_url` para seguridad.

---

### Archivos Limpios (Sin Issues Significativos)

Los siguientes archivos fueron analizados y están limpios:

| Archivo | Líneas | Estado |
|---------|--------|--------|
| `src/iwa/core/services/plugin.py` | ~50 | ✅ Limpio |
| `src/iwa/plugins/gnosis/cow_utils.py` | ~60 | ✅ Limpio |
| `src/iwa/plugins/gnosis/safe.py` | ~100 | ✅ Limpio |
| `src/iwa/plugins/olas/constants.py` | ~80 | ✅ Limpio |
| `src/iwa/plugins/olas/models.py` | ~120 | ✅ Limpio |
| `src/iwa/plugins/olas/contracts/base.py` | ~30 | ✅ Limpio |
| `src/iwa/plugins/olas/contracts/activity_checker.py` | ~80 | ✅ Limpio |
| `src/iwa/plugins/olas/contracts/service.py` | ~200 | ✅ Limpio |
| `src/iwa/tui/rpc.py` | ~100 | ✅ Limpio |
| `src/iwa/tools/check_profile.py` | ~50 | ✅ Limpio |
| `src/iwa/tools/reset_env.py` | ~40 | ✅ Limpio |
| `src/iwa/tools/reset_tenderly.py` | ~60 | ✅ Limpio |
| `src/iwa/tools/restore_backup.py` | ~80 | ✅ Limpio |

---

### Frontend JavaScript (Análisis de Alto Nivel)

Los archivos JavaScript del frontend fueron revisados y presentan estos patrones:

| Archivo | Líneas | Observación |
|---------|--------|-------------|
| `main.js` | ~90 | ✅ Entry point bien organizado |
| `modules/api.js` | ~50 | ✅ Fetch wrapper correcto |
| `modules/auth.js` | ~60 | ✅ Manejo de auth headers |
| `modules/state.js` | ~40 | ✅ Estado global simple |
| `modules/accounts.js` | ~150 | P3: Considerar dividir |
| `modules/olas.js` | ~300 | P2: Archivo largo, dividir |
| `modules/cowswap.js` | ~200 | P3: Considerar dividir |
| `modules/modals.js` | ~250 | P2: Muchas funciones similares |
| `modules/transactions.js` | ~100 | ✅ Limpio |
| `modules/rpc.js` | ~80 | ✅ Limpio |
| `modules/ui.js` | ~100 | ✅ Limpio |
| `modules/utils.js` | ~60 | ✅ Limpio |

**Recomendaciones Frontend:**

| ID | Prioridad | Problema | Solución Propuesta |
|----|-----------|----------|-------------------|
| FE-S1 | P2 | JS inline en `index.html` (CSP 'unsafe-inline') | Mover todo JS a módulos |
| FE-C1 | P2 | `modules/olas.js` muy largo | Dividir en `olas_services.js`, `olas_staking.js` |
| FE-C2 | P3 | Funciones de modal duplicadas | Crear factory de modales |

---

## Estadísticas Finales

| Categoría | Archivos Analizados | Limpios | Con Issues |
|-----------|---------------------|---------|------------|
| Core | 15 | 8 | 7 |
| Services | 6 | 3 | 3 |
| Contracts | 5 | 2 | 3 |
| Plugins Gnosis | 4 | 3 | 1 |
| Plugins Olas | 8 | 5 | 3 |
| Web Backend | 6 | 2 | 4 |
| Web Frontend | 12 | 8 | 4 |
| TUI | 6 | 5 | 1 |
| Tools | 4 | 4 | 0 |
| **TOTAL** | **66** | **40** | **26** |

---

## Conclusión

El codebase tiene una base sólida con buenas prácticas en la mayoría de archivos pequeños. Los problemas críticos se concentran en:

1. **Archivos muy largos** (`service_manager.py`, `transfer.py`, `olas.py`) que necesitan división urgente
2. **Complejidad ciclomática** (múltiples `# noqa: C901`) que dificulta mantenimiento
3. **Algunas vulnerabilidades de seguridad** (whitelist bypass, claves en memoria) que requieren atención inmediata

El plan de 4 sprints propuesto prioriza correctamente la seguridad primero, seguido de arquitectura y código limpio.

---

## Checklist de Implementación

> **Instrucciones**: Marcar con `[x]` las tareas completadas. Cada tarea incluye el archivo a modificar y la acción específica a realizar.

---

### Sprint 1: Seguridad Crítica (P0/P1)

#### 1.1 Fix Whitelist Bypass (TRANS-S1) - **P0**
- [x] **Archivo**: `src/iwa/core/services/transfer.py`
- [x] **Línea**: Método `_is_whitelisted_destination()`
- [x] **Acción**: Añadir check fail-closed al inicio del método:
  ```python
  def _is_whitelisted_destination(self, address: str) -> bool:
      if not self.config.core:
          logger.warning("No core config found, rejecting destination")
          return False  # Fail-closed
      # ... resto del método
  ```
- [x] **Test**: Añadir test en `test_transfer.py` que verifique rechazo cuando `config.core` es None

#### 1.2 Documentar get_signer() (KEYS-S4) - **P0**
- [x] **Archivo**: `src/iwa/core/keys.py`
- [x] **Línea**: Método `get_signer()` (~línea 280)
- [x] **Acción**: Añadir docstring con advertencia de seguridad:
  ```python
  def get_signer(self, address_or_tag: str) -> Optional[LocalAccount]:
      """Get LocalAccount signer for external APIs like CowSwap.

      ⚠️ SECURITY WARNING: This returns a LocalAccount with accessible
      private key (.key property). Only use when external library requires
      a signer object. Never log or expose the returned object.

      For signing transactions internally, use sign_transaction() instead.
      """
  ```

#### 1.3 Limpiar Claves en Memoria (SAFE-S2) - **P1**
- [x] **Archivo**: `src/iwa/core/services/safe.py`
- [x] **Línea**: Método `_sign_and_execute_safe_tx()` (~línea 235)
- [x] **Acción**: Añadir limpieza explícita de claves después de uso:
  ```python
  def _sign_and_execute_safe_tx(self, safe_tx: SafeTx, signer_keys: List[str]):
      try:
          # ... código existente de firma y ejecución ...
          return tx_hash
      finally:
          # SECURITY: Clear sensitive data from memory
          for i in range(len(signer_keys)):
              signer_keys[i] = "0" * 64
          signer_keys.clear()
  ```

#### 1.4 Sanitizar RPC URLs en Logs (CHAIN-S1) - **P1**
- [x] **Archivo**: `src/iwa/core/chain.py`
- [x] **Acción 1**: Crear función helper:
  ```python
  def _sanitize_rpc_url(url: str) -> str:
      """Remove API keys from RPC URLs for safe logging."""
      import re
      # Remove query params that might contain keys
      sanitized = re.sub(r'\?.*$', '?***', url)
      # Remove path segments that look like API keys (32+ hex chars)
      sanitized = re.sub(r'/[a-fA-F0-9]{32,}', '/***', sanitized)
      return sanitized
  ```
- [x] **Acción 2**: Reemplazar todos los `logger.info/debug/error` que contengan URLs RPC con versión sanitizada
- [x] **Buscar**: `grep -n "rpc" src/iwa/core/chain.py | grep -i log`

#### 1.5 Permisos en MnemonicStorage.save() (MNEM-S1) - **P1**
- [x] **Archivo**: `src/iwa/core/mnemonic.py`
- [x] **Línea**: Método `MnemonicStorage.save()` (~línea 200)
- [x] **Acción**: Añadir chmod después de guardar:
  ```python
  def save(self, encrypted: EncryptedMnemonic, file_path: Path) -> None:
      with open(file_path, 'w') as f:
          json.dump(encrypted.model_dump(), f)
      os.chmod(file_path, 0o600)  # Solo lectura/escritura para owner
  ```

#### 1.6 Whitelist Explícita para Tokens (TRANS-S2) - **P1**
- [x] **Archivo**: `src/iwa/core/services/transfer.py`
- [x] **Línea**: Método `_is_supported_token()`
- [x] **Acción**: Cambiar lógica para requerir token en whitelist:
  ```python
  def _is_supported_token(self, token_address: str, chain: SupportedChain) -> bool:
      if token_address == NATIVE_CURRENCY_ADDRESS:
          return True
      # Requerir que el token esté explícitamente definido
      if chain.get_token_address(token_address):
          return True
      logger.warning(f"Token {token_address} not in allowed list for {chain.name}")
      return False
  ```

#### 1.7 Reemplazar print() con logger (DB-C1) - **P1**
- [x] **Archivo**: `src/iwa/core/db.py`
- [x] **Acción**: Buscar y reemplazar todos los `print()`:
  ```bash
  # Ejecutar para encontrar:
  grep -n "print(" src/iwa/core/db.py
  ```
- [x] Reemplazar cada `print(...)` con `logger.info(...)` o `logger.error(...)`

---

### Sprint 2: Refactorización Arquitectónica

#### 2.1 Dividir service_manager.py (SM-A1) - **P0** - ✅ **COMPLETADO**
- [x] **Archivo**: `src/iwa/plugins/olas/service_manager.py` (2000+ líneas)
- [x] **Paso 1**: Crear directorio `src/iwa/plugins/olas/service_manager/`
- [x] **Paso 2**: Crear `__init__.py` que re-exporte ServiceManager
- [x] **Paso 3**: Extraer `lifecycle.py`
- [x] **Paso 4**: Extraer `staking.py`
- [x] **Paso 5**: Extraer `drain.py`
- [x] **Paso 6**: Extraer `mech.py`


#### 2.2 Dividir transfer.py (TRANS-A1) - **P1** - ✅ **COMPLETADO**
- [x] **Archivo**: `src/iwa/core/services/transfer.py` (1357 líneas)
- [x] **Paso 1**: Extraer a `transfer_native.py`: métodos de transferencia nativa (Implementado en `native.py`)
- [x] **Paso 2**: Extraer a `transfer_erc20.py`: métodos de transferencia ERC20 (Implementado en `erc20.py`)
- [x] **Paso 3**: Extraer a `multi_send.py`: métodos multi_send (Implementado en `multisend.py`)
- [x] **Paso 4**: Extraer a `swap.py`: integración CowSwap (Implementado en `swap.py`)
- [x] **Paso 5**: Mantener `transfer.py` como facade que importa submódulos (Reemplazado por package `src/iwa/core/services/transfer/`)
- [x] **Test**: Ejecutar tests relacionados con transfer

#### 2.3 Dividir olas.py router (OLAS-R-A1) - **P0**
- [ ] **Archivo**: `src/iwa/web/routers/olas.py` (975 líneas)
- [ ] **Paso 1**: Crear `olas_services.py`: endpoints CRUD de servicios
- [ ] **Paso 2**: Crear `olas_staking.py`: endpoints stake/unstake/checkpoint
- [ ] **Paso 3**: Crear `olas_admin.py`: endpoints fund/drain
- [ ] **Paso 4**: Actualizar `server.py` para incluir nuevos routers
- [ ] **Test**: Probar endpoints manualmente o con tests

#### 2.4 Dividir cow.py (COW-A1) - **P1**
- [ ] **Archivo**: `src/iwa/plugins/gnosis/cow.py` (538 líneas)
- [ ] **Paso 1**: Extraer a `cow_swap.py`: clase CowSwap y método swap()
- [ ] **Paso 2**: Extraer a `cow_quotes.py`: métodos get_*_amount_wei
- [ ] **Paso 3**: Mantener `cow.py` como re-exportador o eliminar
- [ ] **Test**: Ejecutar tests de swap

---

### Sprint 3: Código Limpio (Eliminar C901)

#### 3.1 Refactorizar check_activity() (MON-C1) - **P1**
- [ ] **Archivo**: `src/iwa/core/monitor.py`
- [ ] **Línea**: Método `check_activity()` (~línea 63, 134 líneas)
- [ ] **Acción**: Dividir en métodos helper:
  - [ ] Crear `_should_check() -> bool`
  - [ ] Crear `_get_block_range() -> Tuple[int, int]`
  - [ ] Crear `_check_native_transfers(from_block, to_block) -> List[Dict]`
  - [ ] Crear `_check_erc20_transfers(from_block, to_block) -> List[Dict]`
- [ ] **Resultado**: check_activity() debe tener <20 líneas
- [ ] Eliminar `# noqa: C901`

#### 3.2 Refactorizar create_safe() (SAFE-C1) - **P1**
- [ ] **Archivo**: `src/iwa/core/services/safe.py`
- [ ] **Línea**: Método `create_safe()` (~línea 40, 150 líneas)
- [ ] **Acción**: Dividir en:
  - [ ] `_prepare_safe_deployment()`: validación y preparación
  - [ ] `_execute_deployment()`: transacción de deploy
  - [ ] `_save_safe_to_wallet()`: persistencia
- [ ] Eliminar `# noqa: C901`

#### 3.3 Refactorizar sign_and_send() (TXN-C1) - **P1**
- [ ] **Archivo**: `src/iwa/core/services/transaction.py`
- [ ] **Línea**: Método `sign_and_send()` con `# noqa: C901`
- [ ] **Acción**: Extraer:
  - [ ] `_prepare_transaction()`: preparación y nonce
  - [ ] `_execute_with_retry()`: loop de retry
  - [ ] `_handle_transaction_result()`: logging y DB
- [ ] Eliminar `# noqa: C901`

#### 3.4 Refactorizar get_staking_contracts() (OLAS-R-C1) - **P1**
- [ ] **Archivo**: `src/iwa/web/routers/olas.py`
- [ ] **Línea**: Función `get_staking_contracts()` (~línea 36)
- [ ] **Acción**:
  - [ ] Extraer función interna `check_availability()` a nivel de módulo
  - [ ] Simplificar lógica de filtrado
- [ ] Eliminar `# noqa: C901`

#### 3.5 Refactorizar multi_send() (TRANS-A2) - **P2**
- [ ] **Archivo**: `src/iwa/core/services/transfer.py`
- [ ] **Línea**: Método `multi_send()` con `# noqa: C901`
- [ ] **Acción**: Extraer helpers para validación y preparación
- [ ] Eliminar `# noqa: C901`

---

### Sprint 4: Mejoras Menores

#### 4.1 Eliminar función trace() de TUI (TUI-C1) - **P2**
- [ ] **Archivo**: `src/iwa/tui/app.py`
- [ ] **Línea**: Función `trace()` (líneas 15-22)
- [ ] **Acción**: Eliminar función y todas las llamadas a `trace()` en el archivo
- [ ] Usar `logger.debug()` si se necesita debugging

#### 4.2 Rate Limiting en Swap (SWAP-S1) - **P2**
- [ ] **Archivo**: `src/iwa/web/routers/swap.py`
- [ ] **Línea**: Endpoint `swap_tokens()` (~línea 77)
- [ ] **Acción**: Añadir decorador:
  ```python
  @router.post("/swap")
  @limiter.limit("10/minute")
  def swap_tokens(request: Request, req: SwapRequest, ...):
  ```
- [ ] Añadir `request: Request` como primer parámetro

#### 4.3 Rate Limiting en Olas Críticos (OLAS-R-S1) - **P2**
- [ ] **Archivo**: `src/iwa/web/routers/olas.py`
- [ ] **Endpoints a modificar**:
  - [ ] `stake_service()`: añadir `@limiter.limit("5/minute")`
  - [ ] `terminate_service()`: añadir `@limiter.limit("3/minute")`
  - [ ] `drain_service()`: añadir `@limiter.limit("3/minute")`
- [ ] Añadir import: `from slowapi import Limiter`
- [ ] Añadir `request: Request` como primer parámetro en cada uno

#### 4.4 CSP sin unsafe-inline (SRV-S1) - **P2**
- [ ] **Archivo**: `src/iwa/web/server.py`
- [ ] **Línea**: SecurityHeadersMiddleware CSP
- [ ] **Acción**: Refactorizar para usar nonces o eliminar JS inline
- [ ] **Dependencia**: Primero mover JS inline de index.html a módulos (FE-S1)

#### 4.5 Mover Modelos Web (ACC-A1) - **P3**
- [ ] **Archivo origen**: `src/iwa/web/routers/accounts.py`
- [ ] **Archivo destino**: Crear `src/iwa/web/models.py`
- [ ] **Acción**: Mover `AccountCreateRequest` y `SafeCreateRequest`
- [ ] Actualizar imports en `accounts.py`

#### 4.6 Eliminar Comentario Duplicado (CLI-C1) - **P3**
- [ ] **Archivo**: `src/iwa/core/cli.py`
- [ ] **Líneas**: 193-194 (comentarios `# Load Plugins` duplicados)
- [ ] **Acción**: Eliminar una de las líneas duplicadas

#### 4.7 Mover Import de Time (ACC-C1) - **P3**
- [ ] **Archivo**: `src/iwa/web/routers/accounts.py`
- [ ] **Línea**: Dentro de `create_safe()` hay `import time`
- [ ] **Acción**: Mover import al inicio del archivo

---

### Verificación Final

- [ ] Ejecutar `just check` - debe pasar sin errores
- [ ] Ejecutar `just test` - todos los tests deben pasar
- [ ] Ejecutar `just format` - código formateado
- [ ] Revisar que no hay nuevos `# noqa: C901`
- [ ] Crear commit con mensaje descriptivo para cada sprint

---

## Notas para el Ingeniero Implementador

1. **Orden de Implementación**: Seguir los sprints en orden. Sprint 1 (seguridad) es bloqueante.

2. **Tests**: Cada cambio debe incluir tests. Si no existen, crearlos primero.

3. **Commits**: Un commit por tarea, no commits gigantes por sprint.

4. **Review**: Solicitar PR review para cambios P0 y P1.

5. **Backups**: Antes de refactorizar archivos grandes, asegurar que hay commits limpios.

6. **Documentación**: Actualizar docstrings afectados por refactorizaciones.

