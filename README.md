# IV-2-9 — Designing a Thread Pool (Worker activity)

**F.CSM302 Үйлдлийн систем · Бие даалт 1**
Сурах бичиг: *Operating System Concepts* (Silberschatz, Galvin, Gagne, 2018), 7-р бүлэг, **Programming Project 1 — Designing a Thread Pool** (POSIX хувилбар).
UI дүрслэл: **Worker activity** — worker бүрийн `idle → running → completed` төлөвийг хугацааны явцад харуулна.

## Зорилго

Pthreads, POSIX mutex, semaphore ашиглан номын API-тай (`pool_init`, `pool_submit`, `pool_shutdown`) thread pool хэрэгжүүлэх. Мөн worker-ийн тоо, queue-ийн багтаамж болон ачааллыг өөрчилж дахин турших боломж бүрдүүлэх. Программын бодит үйл явдлын бүртгэлийг (trace) interactive UI дээр алхамчилж харуулна.

## Quick Start

Linux (Ubuntu 22.04+), WSL2 эсвэл macOS дээр `gcc`/`clang`, `make`, `python3` хэрэгтэй.

```bash
git clone https://github.com/NominjinNomio/F.CSM302-BD_IV-2-9-threadpool.git && cd F.CSM302-BD_IV-2-9-threadpool
make            # build/threadpool_sim ба build/client-ийг хөрвүүлнэ
make test       # 29 тест (үндсэн + boundary + буруу оролт) → "Нийт: 29 PASS, 0 FAIL"
make ui         # http://localhost:8000 нээгээд "▶ Ажиллуулах"
```

Командын мөрөөс шууд ажиллуулах:

```bash
./build/threadpool_sim -w 3 -q 5 -n 15 -d 200-800 -a 20-120 -o build/trace.json
./build/threadpool_sim -w 2 -q 3 -f tests/burst.txt -p retry
./build/client                       # номын client.c жишээ
make tsan                            # ThreadSanitizer-ээр race шалгах
```

## Бүтэц

```
src/threadpool.h, threadpool.c   Thread pool (номын API + pool_init_ex, trace)
src/main.c                       Туршилтын программ: CLI параметр, task үүсгэх, JSON trace, шалгалт
examples/client.c                Номын client.c-тэй ижил жишээ
examples/sample_*.json           Сервергүй үзэх боломжтой бэлэн trace
tools/server.py                  UI ↔ C программыг холбох HTTP сервер (Python stdlib)
ui/index.html                    Worker activity interactive UI (гадны сангүй)
tests/*.txt                      Task-ийн файлууд (bad_*.txt — буруу оролтын тест)
tests/run_tests.sh               Бүх тест, tests/verify_trace.py — trace-ийг бие даан шалгагч
tests/experiments.sh             Тайлангийн туршилтын хүснэгтүүдийг дахин гаргана
docs/                            Report.pdf, Manual.pdf, туршилтын CSV
docs/latex/                      Тайлан, Manual-ийн LaTeX эх (Overleaf төсөл), зураг, фонт
```

## Гол шийдлүүд

| Номын шаардлага | Хэрэгжүүлэлт |
|---|---|
| `pool_init()` thread, mutex, semaphore үүсгэх | `pool_init()` = 3 worker, queue 10; `pool_init_ex(n, cap)` тохируулах боломжтой |
| `pool_submit()` → `enqueue()`, массив дүүрвэл 1 | Тойрог массив, дүүрвэл `1` (POOL_FULL) буцааж `REJECT` бүртгэнэ |
| `worker()` semaphore дээр хүлээж `dequeue()` → `execute()` | `sem_wait(work_available)` → mutex дор dequeue → mutex-ээс гадуур execute |
| Queue-г mutex-ээр хамгаалах | `qmutex` — enqueue/dequeue/тоолуур бүгд түүний дор |
| `pool_shutdown()` → thread-үүдийг зогсоож `pthread_join` | shutdown флаг + worker бүрт `sem_post` → үлдсэн task-уудыг гүйцээгээд гарна → `pthread_join` |

## AI ба бэлэн код ашигласан тухай

- Номын API нэр, бүтцийг (`pool_init/pool_submit/pool_shutdown`, `client.c`-ийн жишээ) сурах бичгийн тайлбараас авсан.
- Код, UI, тест, баримт бичгийн анхны хувилбарыг **AI туслахын** тусламжтай бэлтгэсэн. Баг бүх кодыг уншиж, ажиллуулж, тестээр шалгасан. Тайлангийн 5-р хэсэгт аль хэсгийг хэн шалгаж, өөрчилсөнийг тэмдэглэнэ.
- Гадны сан ашиглаагүй: C — зөвхөн libc/pthread; сервер — Python стандарт сан; UI — цэвэр HTML/JS.

## Баримт бичиг

- `docs/IV-2-9_BD1_Report.pdf` — судалгаа, хэрэгжилт, туршилтын тайлан
- `docs/IV-2-9_Manual.pdf` — хэрэглэгчийн ба operational заавар
- `docs/latex/` — хоёр баримтын LaTeX эх (`report.tex`, `manual.tex`, загвар `shutis.sty`).
  Overleaf: `docs/IV-2-9_overleaf.zip`-ийг **New Project → Upload Project**-оор оруулж,
  Menu → Compiler: **XeLaTeX**, Main document: `report.tex` эсвэл `manual.tex`.
  Локал: `cd docs/latex && latexmk` (XeLaTeX).
- Тоо баримтыг шинэчилж дахин үүсгэх: `make && sh tests/run_tests.sh > build/test_output.txt &&
  sh tests/experiments.sh && python3 tools/build_docs.py`

## Гишүүд

| Гишүүн | Оюутны код |
|---|---|
| Ц.Номинжин | B241940137 |
| Е.Айсауле | B221940407 |
| Б.Балжинням | B231940033 |
| М.Бат-Орших | B200930061 |
| Г.Хулан | B241940027 |
| Э.Энхсайхан | B242270097 |
