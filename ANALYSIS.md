# ANALYSIS.md - Auditoría de Patrones de Código

> **Fecha**: 2026-01-06
> **Enfoque**: Return Early, Negative Programming, Reducción de Nesting, Eliminación de noqa

---

## Resumen Ejecutivo

Se identificaron **25 métodos con `# noqa: C901`** (complejidad ciclomática excesiva) en **15 archivos**.

| Archivo | # noqa C901 | Líneas | Prioridad |
|---------|-------------|--------|-----------|
| `lifecycle.py` | 5 | 737 | **CRÍTICA** |
| `importer.py` | 4 | ~500 | ALTA |
| `olas_view.py` | 3 | ~900 | MEDIA |
| `staking.py` | 2 | ~400 | ALTA |
| Otros (11 archivos) | 1 c/u | - | BAJA |

---

## Patrones Problemáticos Identificados

### 1. Nesting Excesivo (>3 niveles)
El código tiene muchos bloques anidados que dificultan la lectura.

### 2. Falta de Return Early
En lugar de salir temprano en condiciones de error, el código continúa con else/if anidados.

### 3. Falta de Negative Programming
La lógica positiva (happy path) se anida dentro de múltiples condiciones en lugar de rechazar casos inválidos primero.

### 4. Métodos Largos
Métodos de 100+ líneas que deberían dividirse en funciones más pequeñas.

---

## Checklist de Refactorización

> **Instrucciones**: Marcar `[x]` al completar. Cada tarea incluye problema y solución.

---

### 1. `src/iwa/plugins/olas/service_manager/lifecycle.py` (5 noqa)

#### 1.1 `create()` (L24-162) - 138 líneas

- [x] **Problema**: Método muy largo con múltiples responsabilidades
- [x] **Solución**: Dividir en métodos auxiliares:
  ```python
  def create(...):
      agent_params = self._prepare_agent_params(agent_ids, bond_amount_wei)
      tx = self._send_create_transaction(agent_params, ...)
      if not tx:
          return None
      service_id = self._extract_service_id_from_receipt(tx)
      if not service_id:
          return None
      self._save_new_service(service_id, ...)
      self._approve_token_if_needed(service_id, token_address, ...)
      return service_id
  ```
- [x] Eliminar `# noqa: C901`

#### 1.2 `activate_registration()` (L164-262) - Nesting 4 niveles

- [x] **Problema**: Líneas 187-231 tienen 4 niveles de nesting:
  ```python
  if not is_native:           # nivel 1
      try:                    # nivel 2
          if utility_address: # nivel 3
              if allowance < X: # nivel 4
  ```
- [x] **Solución**: Aplicar return early y extraer lógica:
  ```python
  def activate_registration(self) -> bool:
      if not self._validate_pre_registration_state():
          return False

      if self._is_token_based_service():
          if not self._ensure_token_approval():
              logger.warning("Token approval failed")

      return self._send_activation_transaction()
  ```
- [x] Eliminar `# noqa: C901`

#### 1.3 `register_agent()` (L264-382) - 118 líneas

- [x] **Problema**: Lógica de creación de agente mezclada con registro
- [x] **Solución**: Extraer:
  ```python
  def _get_or_create_agent(self, agent_address) -> str:
      if agent_address:
          return agent_address
      return self._create_and_fund_agent()

  def _create_and_fund_agent(self) -> str:
      agent = self.wallet.key_storage.create_account(...)
      self._fund_agent(agent.address)
      return agent.address
  ```
- [x] Eliminar `# noqa: C901`

#### 1.4 `spin_up()` (L533-643) - 110 líneas

- [x] **Problema**: 4 bloques if secuenciales para estados
- [x] **Solución**: Usar diccionario de transiciones:
  ```python
  STATE_HANDLERS = {
      ServiceState.PRE_REGISTRATION: "_handle_pre_registration",
      ServiceState.ACTIVE_REGISTRATION: "_handle_active_registration",
      ServiceState.FINISHED_REGISTRATION: "_handle_finished_registration",
      ServiceState.DEPLOYED: "_handle_deployed",
  }

  def spin_up(self, ...):
      current_state = self._get_current_state()
      while current_state != ServiceState.DEPLOYED:
          handler = getattr(self, self.STATE_HANDLERS.get(current_state))
          if not handler():
              return False
          current_state = self._get_current_state()
      return True
  ```
- [x] Eliminar `# noqa: C901`

#### 1.5 `wind_down()` (L645-736) - 91 líneas

- [x] **Problema**: Similar a spin_up, bloques if secuenciales
- [x] **Solución**: Misma estrategia de state machine
- [x] Eliminar `# noqa: C901`

---

### 2. `src/iwa/plugins/olas/importer.py` (4 noqa)

#### 2.1 `_parse_trader_runner_format()` (L135)

- [x] **Problema**: Múltiples try/except anidados
- [x] **Solución**: Extraer validadores:
  ```python
  def _parse_trader_runner_format(self, folder):
      config = self._try_load_config(folder)
      if not config:
          return None

      service = self._extract_service_from_config(config)
      if not self._validate_service(service):
          return None

      return service
  ```
- [x] Eliminar `# noqa: C901`

#### 2.2 `_parse_operate_format()` (L197)

- [x] **Problema**: Similar al anterior
- [x] **Solución**: Aplicar mismo patrón de extracción
- [x] Eliminar `# noqa: C901`

#### 2.3 `_parse_operate_service_config()` (L254)

- [x] **Problema**: Try/except profundos
- [x] **Solución**: Early return en cada validación
- [x] Eliminar `# noqa: C901`

#### 2.4 `import_service()` (L448)

- [x] **Problema**: Método muy largo
- [x] **Solución**: Dividir en pasos claros
- [x] Eliminar `# noqa: C901`

---

### 3. `src/iwa/plugins/olas/tui/olas_view.py` (3 noqa)

#### 3.1 `on_button_pressed()` (L131)

- [x] **Problema**: Gran switch/if-else para manejar botones
- [x] **Solución**: Usar diccionario de handlers:
  ```python
  BUTTON_HANDLERS = {
      "stake": self._handle_stake_button,
      "unstake": self._handle_unstake_button,
      "fund": self._handle_fund_button,
  }

  def on_button_pressed(self, event):
      handler = self.BUTTON_HANDLERS.get(event.button.id)
      if handler:
          handler()
  ```
- [x] Eliminar `# noqa: C901`

#### 3.2 `stake_service()` (L466)

- [x] **Problema**: Lógica compleja de staking en un método
- [x] **Solución**: Dividir en validación y ejecución
- [x] Eliminar `# noqa: C901`

#### 3.3 `show_create_service_modal()` (L609)

- [x] **Problema**: Construcción de UI mezclada con lógica
- [x] **Solución**: Separar creación de modal de lógica de negocio
- [x] Eliminar `# noqa: C901`

---

### 4. `src/iwa/plugins/olas/service_manager/staking.py` (2 noqa)

#### 4.1 `get_staking_status()` (L18)

- [x] **Problema**: Múltiples condiciones anidadas
- [x] **Solución**: Aplicar early return:
  ```python
  def get_staking_status(self):
      if not self.service:
          return None
      if not self.service.staking_contract_address:
          return StakingStatus.NOT_STAKED
      # ... continuar con caso positivo
  ```
- [x] Eliminar `# noqa: C901`

#### 4.2 `stake()` (L139)

- [x] **Problema**: Validaciones y ejecución mezcladas
- [x] **Solución**: Extraer `_validate_stake_preconditions()` y `_execute_stake()`
- [x] Eliminar `# noqa: C901`

---

### 5. `src/iwa/plugins/olas/service_manager/drain.py` (1 noqa)

#### 5.1 `drain_service()` (L146)

- [x] **Problema**: Método largo con múltiples tipos de drain
- [x] **Solución**: Estrategia pattern:
  ```python
  def drain_service(self, ...):
      results = {}
      results["native"] = self._drain_native(...)
      results["erc20"] = self._drain_erc20_tokens(...)
      results["agent"] = self._drain_agent_account(...)
      return results
  ```
- [x] Eliminar `# noqa: C901`

---

### 6. `src/iwa/core/services/transfer/swap.py` (1 noqa)

#### 6.1 `swap()` (L20)

- [x] **Problema**: Método async largo
- [x] **Solución**: Extraer `_prepare_swap()`, `_execute_swap()`, `_log_swap_result()`
- [x] Eliminar `# noqa: C901`

---

### 7. `src/iwa/core/db.py` (2 noqa)

#### 7.1 `run_migrations()` (L65)

- [ ] **Problema**: Múltiples migraciones en un solo método
- [ ] **Solución**: Una función por migración:
  ```python
  MIGRATIONS = [
      _migration_add_decimal_info,
      _migration_add_account_type,
      # ...
  ]

  def run_migrations(columns):
      for migration in MIGRATIONS:
          migration(columns)
  ```
- [ ] Eliminar `# noqa: C901`

#### 7.2 `log_transaction()` (L126)

- [ ] **Problema**: Demasiados parámetros y lógica condicional
- [ ] **Solución**: Crear `TransactionLogData` dataclass
- [ ] Eliminar `# noqa: C901, D103`

---

### 8. Archivos con 1 noqa (Prioridad Baja)

#### 8.1 `src/iwa/tools/reset_env.py` - `main()` (L19)
- [ ] Dividir en funciones por tipo de reset
- [ ] Eliminar `# noqa: C901`

#### 8.2 `src/iwa/tools/reset_tenderly.py` - `main()` (L209)
- [ ] Dividir en funciones por operación
- [ ] Eliminar `# noqa: C901`

#### 8.3 `src/iwa/plugins/olas/plugin.py` - `import_services()` (L82)
- [ ] Extraer lógica de descubrimiento y validación
- [ ] Eliminar `# noqa: C901`

#### 8.4 `src/iwa/plugins/gnosis/cow_utils.py` - `get_cowpy_module()` (L9)
- [ ] Simplificar lógica de importación
- [ ] Eliminar `# noqa: C901`

#### 8.5 `src/iwa/tui/screens/wallets.py` - `refresh_table_structure_and_data()` (L158)
- [ ] Dividir estructura de datos de renderizado
- [ ] Eliminar `# noqa: C901`

#### 8.6 `src/iwa/plugins/olas/service_manager/mech.py` - `_send_marketplace_mech_request()` (L124)
- [ ] Aplicar early return pattern
- [ ] Eliminar `# noqa: C901`

---

### 9. Archivos Largos sin noqa (Prioridad Media)

> Estos archivos no tienen noqa pero son muy largos y se beneficiarían de refactorización.

#### 9.1 `src/iwa/core/chain.py` (974 líneas)

- [ ] **Problema**: Archivo muy largo con múltiples clases (ChainInterface, RPCRateLimiter, etc.)
- [ ] **Solución**: Dividir en package:
  ```
  chain/
  ├── __init__.py      # Re-exports
  ├── interface.py     # ChainInterface
  ├── rate_limiter.py  # RPCRateLimiter
  ├── chains.py        # Gnosis, Ethereum, etc.
  └── errors.py        # TenderlyQuotaExceededError
  ```

#### 9.2 `src/iwa/tui/screens/wallets.py` (735 líneas)

- [ ] **Problema**: UI y lógica de datos mezcladas
- [ ] **Solución**: Separar en `wallets_ui.py` (componentes) y `wallets_data.py` (transformación)

#### 9.3 `src/iwa/tui/modals/base.py` (406 líneas)

- [ ] **Problema**: Modal base muy largo con múltiples responsabilidades
- [ ] **Solución**: Extraer modales específicos a archivos propios

#### 9.4 `src/iwa/web/routers/olas/services.py` (378 líneas)

- [ ] **Problema**: Muchos endpoints en un archivo
- [ ] **Solución**: Revisar si endpoints individuales son concisos, considerar sub-dividir

#### 9.5 `src/iwa/plugins/gnosis/cow/swap.py` (374 líneas)

- [ ] **Problema**: Clase CowSwap grande
- [ ] **Solución**: Evaluar extracción de helpers (opcional, ya está en package propio)

---

## Patrones a Aplicar

### Pattern 1: Return Early (Guard Clauses)

**Antes** (nesting profundo):
```python
def process(data):
    if data:
        if data.is_valid:
            if data.has_permission:
                return do_work(data)
            else:
                return "no permission"
        else:
            return "invalid"
    else:
        return "no data"
```

**Después** (return early):
```python
def process(data):
    if not data:
        return "no data"
    if not data.is_valid:
        return "invalid"
    if not data.has_permission:
        return "no permission"
    return do_work(data)
```

### Pattern 2: Negative Programming

**Antes**:
```python
def validate(user):
    if user.is_active:
        if user.has_subscription:
            if not user.is_banned:
                return True
    return False
```

**Después**:
```python
def validate(user):
    if not user.is_active:
        return False
    if not user.has_subscription:
        return False
    if user.is_banned:
        return False
    return True
```

### Pattern 3: Extract Method

**Antes** (método de 100+ líneas):
```python
def big_method(self):
    # 30 lines of validation
    # 40 lines of processing
    # 30 lines of logging
```

**Después**:
```python
def big_method(self):
    if not self._validate():
        return None
    result = self._process()
    self._log_result(result)
    return result
```

### Pattern 4: State Machine para Transiciones

**Antes**:
```python
if state == A:
    do_a()
    state = B
if state == B:
    do_b()
    state = C
# ...
```

**Después**:
```python
TRANSITIONS = {
    A: (do_a, B),
    B: (do_b, C),
}

while state != FINAL:
    handler, next_state = TRANSITIONS[state]
    if not handler():
        return False
    state = next_state
```

---

## Verificación Final

Después de completar todas las tareas:

```bash
# Verificar que no quedan noqa: C901
grep -rn "# noqa: C901" src/iwa --include="*.py" | wc -l
# Debe ser 0

# Verificar linters
just check

# Verificar tests
just test
```

---

## Notas para el Ingeniero

1. **Un método a la vez**: No refactorizar todo de golpe
2. **Tests primero**: Si no hay test, créalo antes de refactorizar
3. **Commits atómicos**: Un commit por método refactorizado
4. **Verificar**: `just test` después de cada cambio
5. **Documentar**: Actualizar docstrings si cambia la firma

---

## Inventario Completo de Archivos

> 94 archivos Python analizados (16,857 líneas totales)

### Archivos Críticos (Requieren Refactorización)

| Archivo | Líneas | noqa | Problema Principal |
|---------|--------|------|-------------------|
| `service_manager/lifecycle.py` | 737 | 5 | Métodos >100 líneas, nesting profundo |
| `olas/importer.py` | 668 | 4 | Try/except anidados, parsing complejo |
| `tui/olas_view.py` | 916 | 3 | Event handler con muchos branches |
| `service_manager/staking.py` | 510 | 2 | Validaciones mezcladas con ejecución |
| `core/chain.py` | 974 | 0 | Archivo muy largo, múltiples responsabilidades |
| `tui/screens/wallets.py` | 735 | 1 | Refresh complejo, UI mezclada con datos |

### Archivos con Issues Menores

| Archivo | Líneas | noqa | Issue |
|---------|--------|------|-------|
| `service_manager/drain.py` | 324 | 1 | drain_service() largo |
| `service_manager/mech.py` | 312 | 1 | Request handling complejo |
| `plugins/olas/plugin.py` | 252 | 1 | import_services() largo |
| `core/db.py` | 224 | 2 | Migraciones y logging |
| `tools/reset_tenderly.py` | 343 | 1 | main() script largo |
| `tools/reset_env.py` | ~100 | 1 | main() con muchos resets |
| `gnosis/cow_utils.py` | ~80 | 1 | Import dinámico complejo |
| `core/services/transfer/swap.py` | ~300 | 1 | swap() async largo |

### Archivos Bien Estructurados ✅

Los siguientes archivos tienen buena estructura y no requieren cambios:

| Categoría | Archivos |
|-----------|----------|
| **Core Services** | `account.py` (58), `balance.py` (114), `transaction.py` (166) |
| **Transfer Mixins** | `base.py` (260), `native.py` (262), `erc20.py` (247), `multisend.py` (381) |
| **Contracts** | `contract.py` (297), `erc20.py` (80), `multisend.py` (72) |
| **Core** | `types.py` (60), `utils.py` (60), `plugins.py` (46), `tables.py` (61) |
| **Web** | `server.py` (147), `dependencies.py` (77) |
| **Routers** | `accounts.py` (190), `transactions.py` (154), `state.py` (66) |
| **Models** | `models.py` (344), `keys.py` (361), `mnemonic.py` (385) |
| **Plugins Gnosis** | `plugin.py` (69), `cow/swap.py` (374) |
| **TUI** | `app.py` (193), `rpc.py` (~100), `modals/base.py` (406) |

---

## Análisis Detallado por Categoría

### Core Services (Limpio ✅)

- `account.py`: Servicio simple, bien estructurado
- `balance.py`: Retry logic implementado correctamente
- `transaction.py`: Sign and send con reintentos, aceptable
- `safe.py` (392 líneas): **Revisar** - `create_safe()` es largo pero ya fue refactorizado

### Transfer Mixins (Limpio ✅)

Los mixins de transfer están bien divididos:
- `base.py`: Validaciones y helpers compartidos
- `native.py`: Transferencias de moneda nativa
- `erc20.py`: Transferencias ERC20, approvals
- `multisend.py`: Operaciones batch

### Web Routers

| Router | Líneas | Estado |
|--------|--------|--------|
| `olas/services.py` | 378 | **Revisar** - Muchos endpoints |
| `olas/staking.py` | 341 | Aceptable |
| `olas/admin.py` | ~150 | ✅ |
| `olas/funding.py` | ~100 | ✅ |
| `swap.py` | 313 | Tiene 1 noqa |

### Olas Contracts (Limpio ✅)

- `staking.py` (403): Bien documentado
- `service.py` (215): Contratos de servicio
- `mech.py`, `mech_marketplace.py`: Integración Mech
- `activity_checker.py`: Checker de actividad

---

## Resumen de Trabajo

| Prioridad | Archivos | Tareas | Esfuerzo |
|-----------|----------|--------|----------|
| **CRÍTICA** | 6 | 25 | 2-3 días |
| **ALTA** | 8 | 15 | 1-2 días |
| **MEDIA** | 5 | 8 | 1 día |
| **BAJA** | 75 | 0 | - |
| **TOTAL** | 94 | 48 | ~5 días |

---

## Orden de Implementación Sugerido

### Día 1: Lifecycle (Crítico)
1. Refactorizar `create()` en lifecycle.py
2. Refactorizar `activate_registration()`
3. Refactorizar `register_agent()`

### Día 2: Lifecycle + Staking
4. Refactorizar `spin_up()` con state machine
5. Refactorizar `wind_down()`
6. Refactorizar `stake()` en staking.py

### Día 3: Importer + TUI
7. Refactorizar métodos de parsing en importer.py
8. Refactorizar `on_button_pressed()` en olas_view.py

### Día 4: DB + Tools
9. Refactorizar `run_migrations()` en db.py
10. Cleanup de tools/

### Día 5: Verificación + Chain
11. Verificar todos los tests
12. Evaluar división de chain.py (opcional)


