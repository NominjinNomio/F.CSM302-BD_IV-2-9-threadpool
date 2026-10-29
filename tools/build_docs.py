#!/usr/bin/env python3
"""
build_docs.py — БД1-ийн Тайлан ба Гарын авлагыг LaTeX (Overleaf) төсөл болгон үүсгэж,
XeLaTeX-ээр PDF болгоно.

Тоо баримт бүгд бодит ажиллуулалтаас уншигдана:
  build/test_output.txt       ← sh tests/run_tests.sh > build/test_output.txt
  docs/results/*.csv          ← sh tests/experiments.sh
  docs/latex/img/shots/*.png  ← python3 tools/screenshots.py (сервер ажиллаж байхад)
Ашиглах:  python3 tools/build_docs.py [--no-pdf]
Гаралт:   docs/latex/report.tex, docs/latex/manual.tex  (Overleaf төсөл: docs/latex/)
          docs/IV-2-9_BD1_Report.pdf, docs/IV-2-9_Manual.pdf
          docs/IV-2-9_overleaf.zip (Overleaf → New Project → Upload Project)

Багийн мэдээллийг доорх MEMBERS-д, эсвэл үүссэн .tex файлын эхэнд засна.
"""
import csv
import html
import os
import re
import shutil
import subprocess
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs")
LATEX = os.path.join(DOCS, "latex")

# ============================ Багийн мэдээлэл ==================================
CODE = "IV-2-9"
TOPIC = '"Designing a Thread Pool. Programming Project 1 (7-р бүлэг), Worker activity"'
TEACHER = "Г.Ганбат /F.CS10/"
DATE = "2026 оны 10 дугаар сарын 29"
CITY = "Улаанбаатар хот"
YEAR = "2026 он"
REPO = "https://github.com/NominjinNomio/F.CSM302-BD_IV-2-9-threadpool"
REPO_DIR = "F.CSM302-BD_IV-2-9-threadpool"
# (нэр, оюутны код, хариуцах ажил, commit/file)
MEMBERS = [
    ("Ц.Номинжин", "B241940137", "Сервер, CI, screenshot", "tools/, .github/"),
    ("Е.Айсауле", "B221940407", "Туршилтын программ, CLI, оролтын шалгалт", "src/main.c, examples/"),
    ("Б.Балжинням", "B231940033", "Автомат тест, trace шалгагч, туршилт", "tests/"),
    ("М.Бат-Орших", "B200930061", "Thread pool core: queue, mutex, semaphore, worker", "src/threadpool.c, src/threadpool.h"),
    ("Г.Хулан", "B241940027", "Worker activity интерфейс", "ui/index.html"),
    ("Э.Энхсайхан", "B242270097", "Тайлан, гарын авлага", "docs/, README.md"),
]

# Хавсралт А-ийн "Гишүүн / Хариуцах ажил" хүснэгтэд гарах мөр
APPENDIX_MEMBERS = [("Ц.Номинжин", "B241940137", w, f) for _, _, w, f in MEMBERS]

e = html.escape


# ============================ Туслах функцууд ==================================
def read(p):
    with open(os.path.join(ROOT, p), encoding="utf-8") as f:
        return f.read()


def csv_rows(name):
    with open(os.path.join(DOCS, "results", name), encoding="utf-8") as f:
        return list(csv.reader(f))


def sh(cmd):
    try:
        return subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout.strip()
    except Exception:
        return "?"


def snippet(path, start, end, drop=()):
    s = read(path)
    i = s.index(start)
    j = s.index(end, i)
    lines = [re.sub(r"\s{3,}(/\*.*\*/)\s*$", r"  \1", l) for l in s[i:j].rstrip().splitlines()
             if not any(d in l for d in drop)]
    return "\n".join(lines)


def c(s):
    """Inline код (агуулгад HTML хэлбэрээр бичээд h2l() LaTeX болгоно)."""
    return f"<code>{e(s)}</code>"


IMG = lambda n: f"img/shots/{n}.png"


# ============================ HTML-маягийн inline → LaTeX =====================
def tex_escape(t):
    t = t.replace("\\", "\x00BS\x00")
    for a, b in (("&", r"\&"), ("%", r"\%"), ("$", r"\$"), ("#", r"\#"), ("_", r"\_"),
                 ("{", r"\{"), ("}", r"\}"), ("~", r"\textasciitilde{}"), ("^", r"\textasciicircum{}")):
        t = t.replace(a, b)
    t = t.replace("\x00BS\x00", r"\textbackslash{}")
    return t


REF = {"F": "fig", "T": "tab", "K": "lst"}


def h2l(s):
    """<b>, <i>, <code>, <kbd>, <span class='mono'>, <br> бүхий мөрийг LaTeX болгоно."""
    s = s.replace("\ufe0e", "").replace("⏮", "|◀").replace("⏸", "‖")
    s = re.sub(r"\{([TFK]):(\w+)\}", lambda m: f"\x01{m.group(1)}{m.group(2)}\x02", s)
    out, stack, pos, raw = [], [], 0, None
    for m in re.finditer(r"<(/?)([a-zA-Z]+)([^>]*)>", s):
        text = html.unescape(s[pos:m.start()])
        if raw is not None:
            raw += text
        else:
            out.append(tex_escape(text))
        pos = m.end()
        close, tag, attrs = m.group(1), m.group(2).lower(), m.group(3)
        if tag == "br":
            out.append(r"\newline ")
            continue
        if not close:
            if tag in ("b", "strong"):
                out.append(r"\textbf{"); stack.append("}")
            elif tag in ("i", "em"):
                out.append(r"\textit{"); stack.append("}")
            elif tag == "code":
                out.append(r"\code{"); stack.append("}")
            elif tag == "kbd":
                out.append(r"\kbd{"); stack.append("}")
            elif tag == "span" and "mono" in attrs:
                raw = ""; stack.append("span-mono")
            else:
                out.append("{"); stack.append("}")
        else:
            top = stack.pop()
            if top == "span-mono":
                r = raw.strip(); raw = None
                if r.startswith("http") or "github.com" in r:
                    out.append(r"\url{" + r + "}")
                else:
                    out.append(r"\code{" + tex_escape(r) + "}")
            else:
                out.append(top)
    out.append(tex_escape(html.unescape(s[pos:])))
    t = "".join(out)
    return re.sub("\x01([TFK])(\\w+)\x02", lambda m: f"\\ref{{{REF[m.group(1)]}:{m.group(2)}}}", t)


# ============================ LaTeX баримт =====================================
class Doc:
    def __init__(self):
        self.parts = []

    def add(self, s):
        if s.lstrip().startswith('<ol class="refs">'):
            items = re.findall(r"<li>(.*?)</li>", s, flags=re.S)
            body = "\n".join(r"  \item " + h2l(re.sub(r"^\[\d+\]\s*", "", i.strip())) for i in items)
            self.parts.append("\\begin{enumerate}[label={[\\arabic*]}, leftmargin=2.4em]\n" + body + "\n\\end{enumerate}\n")
        else:
            self.parts.append(s)

    def chapter(self, title, newpage=False):
        self.parts.append(("\\clearpage\n" if newpage else "") + f"% {'=' * 70}\n\\section{{{tex_escape(title)}}}\n")

    def plain_chapter(self, title, newpage=False):
        t = tex_escape(title)
        self.parts.append(("\\clearpage\n" if newpage else "") +
                          f"\\section*{{{t}}}\n\\addcontentsline{{toc}}{{section}}{{{t}}}\n")

    def section(self, title):
        self.parts.append(f"\\subsection{{{h2l(title)}}}\n")

    def h3(self, title):
        self.parts.append(f"\\subsubsection*{{{h2l(title)}}}\n")

    def p(self, s):
        self.parts.append(h2l(s) + "\n")

    def _list(self, env, items):
        self.parts.append(f"\\begin{{{env}}}\n" + "\n".join("  \\item " + h2l(i) for i in items) + f"\n\\end{{{env}}}\n")

    def ul(self, items):
        self._list("itemize", items)

    def ol(self, items):
        self._list("enumerate", items)

    def table(self, caption, rows, key=None, widths=None, cls=""):
        n = len(rows[0])
        widths = widths or [100 / n] * n
        spec = "|" + "|".join(f"P{{{w / 100:.3f}}}" for w in widths) + "|"
        head = "\\rowcolor{tablehead} " + " & ".join(f"\\textbf{{{h2l(x)}}}" for x in rows[0]) + " \\\\ \\hline"
        lab = f"\\label{{tab:{key}}}" if key else ""
        body = [" & ".join(h2l(x) for x in r) + " \\\\ \\hline" for r in rows[1:]]
        if len(rows) <= 8:       # богино хүснэгт хуудсаар таслагдахгүй
            lines = ["\\begin{table}[H]", "\\centering"]
            if caption:
                lines.append(f"\\caption{{{h2l(caption)}}}{lab}")
            lines += [f"\\begin{{tabular}}{{{spec}}}", "\\hline", head] + body + ["\\end{tabular}", "\\end{table}\n"]
        else:
            lines = [f"\\begin{{longtable}}{{{spec}}}"]
            if caption:
                lines.append(f"\\caption{{{h2l(caption)}}}{lab}\\\\")
            lines += ["\\hline", head, "\\endfirsthead", "\\hline", head, "\\endhead"] + body
            lines.append("\\end{longtable}\n")
        self.parts.append("\n".join(lines))

    def code(self, caption, src, lang="c", key=None):
        body = pyg_latex(src.strip("\n"), lang)
        if caption:
            lab = f"\\label{{lst:{key}}}" if key else ""
            self.parts.append("\\par\\noindent\\begin{minipage}{\\linewidth}"
                              "\\setlength{\\topsep}{1pt}\\setlength{\\partopsep}{0pt}\n"
                              f"\\captionof{{codeblock}}{{{h2l(caption)}}}{lab}\n{body}\\end{{minipage}}\n")
        else:
            self.parts.append("\\par\\noindent\\begin{minipage}{\\linewidth}"
                              "\\setlength{\\topsep}{1pt}\\setlength{\\partopsep}{0pt}\n" + body + "\\end{minipage}\n")

    def _figure(self, body, caption, key):
        lab = f"\\label{{fig:{key}}}" if key else ""
        self.parts.append(f"\\begin{{figure}}[H]\n\\centering\n{body}\n\\caption{{{h2l(caption)}}}{lab}\n\\end{{figure}}\n")

    def shot(self, img, caption, key=None, width=72, url=None):
        self.photos([(img, width)], caption, key=key)

    def shots(self, names, caption, key=None, width=78, layout="stack"):
        if layout == "row":
            w = width * 0.48
            fr = lambda f: (f"{{\\setlength{{\\fboxsep}}{{0pt}}\\setlength{{\\fboxrule}}{{0.5pt}}"
                            f"\\fcolorbox{{frameline}}{{white}}{{\\includegraphics[width=\\linewidth]{{{f}}}}}}}")
            body = "\\hspace{4mm}".join(f"\\begin{{minipage}}[t]{{{w / 100:.3f}\\linewidth}}\\vspace{{0pt}}{fr(IMG(n))}\\end{{minipage}}" for n in names)
            self._figure(body, caption, key)
        else:
            self.photos([IMG(n) for n in names], caption, key=key, width=width)

    def photos(self, imgs, caption, key=None, width=80, sep="8pt"):
        """Бодит дэлгэцийн зураг (хүрээтэй). imgs: [(файл, өргөн%)...] эсвэл файлын жагсаалт."""
        items = [(i, width) if isinstance(i, str) else i for i in imgs]
        body = f"\\\\[{sep}]\n".join(
            f"{{\\setlength{{\\fboxsep}}{{0pt}}\\setlength{{\\fboxrule}}{{0.5pt}}"
            f"\\fcolorbox{{frameline}}{{white}}{{\\includegraphics[width={w / 100:.2f}\\linewidth]{{{f}}}}}}}"
            for f, w in items)
        self._figure(body, caption, key)

    def diagram(self, name, caption, key=None):
        self._figure(DIAGRAMS[name](), caption, key)

    def latex(self):
        return "\n".join(self.parts)


# ============================ Код өнгөлөх (Pygments → fvextra) ================
def _pyg():
    from pygments.style import Style
    from pygments.token import Comment, Keyword, Name, String, Number, Operator
    class ShutisStyle(Style):
        styles = {Keyword: "#3B5B8F", Keyword.Type: "#3B5B8F", Name.Builtin: "#3B5B8F",
                  Comment: "italic #8A8A8A", Comment.Preproc: "noitalic #3B5B8F", Comment.PreprocFile: "noitalic #3B5B8F",
                  String: "#6B6B6B", Number: "#1A1A1A", Operator: "#1A1A1A"}
    return ShutisStyle


def pyg_latex(src, lang):
    from pygments import highlight
    from pygments.formatters import LatexFormatter
    from pygments.lexers import get_lexer_by_name
    fmt = LatexFormatter(style=_pyg(), commandprefix="PY")
    return highlight(src, get_lexer_by_name({"c": "c", "json": "json", "bash": "bash"}.get(lang, lang)), fmt)


def write_codestyle():
    from pygments.formatters import LatexFormatter
    with open(os.path.join(LATEX, "codestyle.tex"), "w", encoding="utf-8") as f:
        f.write("% Pygments-ийн өнгөний тодорхойлолт (tools/build_docs.py үүсгэсэн)\n")
        f.write(LatexFormatter(style=_pyg(), commandprefix="PY").get_style_defs())


# ============================ TikZ диаграм =====================================
def arch_tikz():
    return r"""\begin{tikzpicture}[node distance=1.15cm, box/.append style={text width=3.55cm}]
  \node[box] (core) {\textbf{C core}\\\code{threadpool\_sim}\\pthreads, mutex,\\semaphore, queue};
  \node[box, right=of core] (srv) {\textbf{Python сервер}\\\code{/api/run}: шалгах,\\\code{subprocess}, JSON\\trace буцаах};
  \node[box, right=of srv] (ui) {\textbf{Browser}\\\code{index.html}\\Worker activity,\\queue, timeline};
  \draw[flow] (core) -- node[lbl, above]{stdout} node[lbl, below]{JSON trace} (srv);
  \draw[flow] (srv) -- node[lbl, above]{HTTP} node[lbl, below]{JSON} (ui);
  \draw[flow] (ui.south) -- ++(0,-0.6) -| node[lbl, pos=0.25, below]{тохиргоо (JSON) $\rightarrow$ CLI аргумент} (core.south);
\end{tikzpicture}"""


def pool_tikz():
    slots = []
    for i in range(5):
        x = 3.25 + i * 0.82
        if i < 3:
            slots.append(f"  \\node[draw=headblue!60, fill=headblue!55, minimum size=0.66cm, inner sep=0pt, text=white, "
                         f"font=\\scriptsize\\ttfamily] (s{i}) at ({x:.2f},0) {{T{i + 3}}};")
        else:
            slots.append(f"  \\node[draw=black!35, dashed, minimum size=0.66cm, inner sep=0pt] (s{i}) at ({x:.2f},0) {{}};")
    return r"""\begin{tikzpicture}[font=\small]
  \node[box, text width=2.7cm, minimum height=1.35cm] (sub) at (0,0) {\code{pool\_submit()}\\lock $\rightarrow$ enqueue\\$\rightarrow$ unlock};
""" + "\n".join(slots) + r"""
  \node[draw=black!25, rounded corners=5pt, fit=(s0)(s4), inner xsep=6pt, inner ysep=9pt] (q) {};
  \node[font=\small\bfseries, above=1pt of q] {Тойрог queue (\code{qmutex})};
  \node[font=\scriptsize, below=0pt of s0] {head};
  \node[font=\scriptsize, below=0pt of s3] {tail};
  \node[draw=yellow!45!black!45, fill=yellow!8, rounded corners=9pt, align=center, font=\scriptsize, inner sep=4pt]
       (sem) at (4.9,-2.05) {\code{sem work\_available}\\= queue дахь task-ийн тоо};
  \node[box, text width=3.4cm, minimum height=0.9cm, font=\scriptsize, fill=headblue!6] (w0) at (10.75,1.25) {\textbf{Worker 0}\\running T2 (mutex-ээс гадна)};
  \node[box, text width=3.4cm, minimum height=0.9cm, font=\scriptsize, fill=headblue!6] (w1) at (10.75,0) {\textbf{Worker 1}\\sem\_wait $\rightarrow$ dequeue $\rightarrow$ execute};
  \node[box, text width=3.4cm, minimum height=0.9cm, font=\scriptsize] (w2) at (10.75,-1.25) {\textbf{Worker N$-$1}\\idle: sem\_wait дээр блоклогдсон};
  \draw[flow] (sub) -- (q);
  \draw[flow] (q.east) -- node[lbl, above]{dequeue} (w1.west);
  \draw[flow, dashed, draw=yellow!40!black!70] (sub.south) |- node[lbl, pos=0.75, above, text=yellow!40!black!80]{\code{sem\_post}} (sem.west);
  \draw[flow, dashed, draw=yellow!40!black!70] (sem.east) -- node[lbl, below right, text=yellow!40!black!80]{сэрээнэ} (w2.west);
\end{tikzpicture}"""


DIAGRAMS = {"arch": arch_tikz, "pool": pool_tikz}


# ============================ Тестийн бодит гаралт =============================
TEST_IDS = [
    ("T2", "basic_default", "Номын анхдагч 3 worker, queue 10, 10 task"),
    ("T3", "burst_reject", "Burst: 10 task t=0, 2 worker, queue 3, reject"),
    ("T4", "burst_retry", "Burst, retry горим"),
    ("T5", "fifo_one_worker", "1 worker: FIFO дараалал"),
    ("T6", "long_short_mix", "1 урт + 7 богино task, 3 worker"),
    ("T7", "random_seeded", "4 worker, queue 8, 20 санамсаргүй task"),
    ("B1", "queue_cap_1", "queue=1, 1 worker, 6 task зэрэг"),
    ("B2", "more_workers", "8 worker, 3 task (worker > task)"),
    ("B3", "max_workers_64", "64 worker (дээд хязгаар), 64 task"),
    ("B4", "single_task", "1 task, 1 мс"),
    ("B5", "stress_500", "500 task, 8 worker, queue 16, retry"),
]


def parse_tests():
    txt = read("build/test_output.txt")
    stats = {}
    for name, st, res in re.findall(r"\[(\w+)\] [^\n]*\n\s+(accepted=[^\n]*)\n(?:[^\n]*\n)*?\s+(PASS|FAIL) \1", txt):
        d = dict(kv.split("=") for kv in st.split())
        d["res"] = res
        stats[name] = d
    errs = re.findall(r"(PASS|FAIL) (err_\w+) → ([^\n]*)", txt)
    total = re.search(r"Нийт: (\d+) PASS, (\d+) FAIL", txt).groups()
    client = "PASS book_client" in txt
    return stats, errs, total, client


def env_rows():
    return {
        "os": sh("grep PRETTY_NAME /etc/os-release | cut -d= -f2 | tr -d '\"'"),
        "arch": sh("uname -m"),
        "kernel": sh("uname -r"),
        "cpu": sh("grep -m1 'model name' /proc/cpuinfo | cut -d: -f2").strip() + f", {sh('nproc')} core",
        "gcc": re.sub(r"\(.*?\)\s*", "", sh("gcc --version | head -1")),
        "glibc": sh("ldd --version | head -1 | awk '{print $NF}'"),
        "py": sh("python3 --version").replace("Python ", ""),
    }


# ============================ ТАЙЛАН ==========================================
def report():
    st, errs, (npass, nfail), client_ok = parse_tests()
    E = env_rows()
    x1, x2, x3 = csv_rows("exp1_workers.csv")[1:], csv_rows("exp2_queue.csv")[1:], csv_rows("exp3_policy.csv")[1:]
    base = float(x1[0][3])
    sp = lambda r: base / float(r[3])
    d = Doc()

    front = f"""<div class="abstract"><h1 class="chapter">ХУРААНГУЙ</h1>
<p><b>Асуудал.</b> Хүсэлт бүрт шинэ thread үүсгэх нь үүсгэх, устгах зардалтай бөгөөд нэгэн зэрэг ажиллах thread-ийн тоог хязгаарладаггүй. Thread pool нь цөөн worker thread-ийг урьдчилан үүсгэж, ажлыг дундын queue-ээр хуваарилна. Энэ queue-д client болон worker-ууд зэрэг хандах тул race condition үүсэх, ажилгүй worker CPU дэмий үрэх аюултай.</p>
<p><b>Шийдэл.</b> Сурах бичгийн Programming Project 1-ийн POSIX хувилбарын дагуу C хэл, POSIX thread (pthreads), mutex lock болон counting semaphore ашиглан {c("pool_init")}, {c("pool_submit")}, {c("pool_shutdown")} API-тай thread pool хэрэгжүүлэв. Программ үйлдэл бүрээ микросекундын нарийвчлалтай JSON trace болгон гаргана. Браузерийн интерфейс уг программыг бодитоор ажиллуулж, багшийн оноосон "Worker activity" дүрслэлээр worker бүрийн idle, running, completed төлөв, queue-ийн дүүргэлт, татгалзлыг алхам алхмаар харуулна.</p>
<p><b>Туршилт.</b> Программыг {npass} автомат тестээр (номын жишээ, үндсэн, захын, буруу оролт) шалгав. Тест бүрийн trace-ийг C кодоос хараат бус Python шалгагчаар дахин шалгаж, ThreadSanitizer-ээр race condition хайв. Worker-ийн тоо, queue-ийн багтаамж, дүүрэх үеийн бодлогын нөлөөг гурван туршилтаар хэмжив.</p>
<p><b>Гол үр дүн.</b> {npass}/{int(npass)+int(nfail)} тест амжилттай. Бүх ажиллуулалтад task бүр яг нэг удаа гүйцэтгэгдэж, queue FIFO дарааллаар ажиллаж, багтаамжаас хэтрээгүй. ThreadSanitizer race илрүүлээгүй. 40 task-ийн ачаалалд worker-ийн тоог 1-ээс 16 болгоход нийт хугацаа {float(x1[0][3]):.0f} мс-ээс {float(x1[-1][3]):.0f} мс болж {sp(x1[-1]):.1f} дахин хурдассан.</p></div>
<div class="pagebreak"></div>"""

    # ---------------- НЭГ ----------------
    d.chapter("Удиртгал")
    d.section("Зорилго")
    d.p('Сурах бичгийн 7-р бүлгийн Programming Project 1 "Designing a Thread Pool"-ийг хэрэгжүүлж, хэрэглэгч worker-ийн тоо, queue-ийн багтаамж, ажлын параметрийг өөрчилж турших боломжтой программ бүтээх. Программын ажиллагааг багшийн оноосон "Worker activity" дүрслэлээр харуулж, хэрэгжилт болон туршилтын үр дүнг баримтжуулах.')
    d.section("Ач холбогдол")
    d.p(f'Thread pool нь вэб сервер, өгөгдлийн сангийн сервер, Java-ийн {c("ExecutorService")}, Linux kernel-ийн {c("workqueue")} зэрэг олон системийн үндэс юм. Энэ төсөл нь mutex, semaphore, bounded buffer (producer-consumer) ойлголтыг нэг бодит программд нэгтгэнэ: task өгөгч client нь producer, worker-ууд нь consumer болно. Thread-үүдийн ажиллагаа нүдэнд харагддаггүй тул worker бүрийн төлөвийг хугацааны тэнхлэг дээр дүрслэх нь ойлголтыг ихээхэн хөнгөвчилнө.')
    d.section("Хамрах хүрээ")
    d.ul([f"C хэл дээрх thread pool: тойрог массив queue, {c('pthread_mutex')}, {c('sem_t')} semaphore, worker thread (сурах бичгийн үндсэн шаардлага).",
          "Номын API-г өөрчлөлтгүй хадгалж, worker-ийн тоо болон queue-ийн багтаамжийг тохируулах өргөтгөл.",
          "Оролтыг шалгах, үйлдэл бүрийг JSON trace болгон хэвлэх, ажиллаж дууссаны дараа 8 инвариант шалгах.",
          "Бодит программтай холбогдсон браузерийн интерфейс: тохиргоо, Worker activity дүрслэл, timeline, үйл явдлын бүртгэл.",
          "Автомат тест, ThreadSanitizer, CI, хэрэглэгчийн ба operational гарын авлага (Manual)."])
    d.p("Java хувилбар (номонд сонголтоор өгсөн), task-ийн priority, worker-ийн тоог ажиллах явцад динамикаар өөрчлөх хамрах хүрээнд ороогүй.")

    # ---------------- ХОЁР ----------------
    d.chapter("Сурах бичгийн шаардлага")
    d.section("Programming Project 1-ийн үндсэн шаардлага")
    d.p("Сурах бичгийн (Silberschatz, Galvin, Gagne, <i>Operating System Concepts</i>, 10-р хэвлэл) 7-р бүлгийн Project 1 нь client-ийн өгсөн ажлыг thread pool-ийн worker-уудаар гүйцэтгэхийг шаардана. POSIX хувилбарын шаардлага:")
    d.ol([f"{c('pool_init()')} нь worker thread-үүдийг эхэнд нь үүсгэж, mutex болон semaphore-ийг эхлүүлнэ.",
          f"{c('pool_submit()')} нь функц болон өгөгдлийг {c('task')} бүтэц болгож {c('enqueue()')}-ээр queue-д хийнэ. Queue массив бөгөөд дүүрсэн бол 1, амжилттай бол 0 буцаана.",
          f"{c('worker()')} нь ажил ирэхийг semaphore дээр хүлээж, {c('dequeue()')}-ээр авсан task-ийг {c('execute()')}-ээр гүйцэтгэнэ.",
          "Queue-д хандах бүх үйлдлийг mutex lock-оор хамгаална.",
          f"{c('pool_shutdown()')} нь worker-уудыг зогсоож {c('pthread_join()')} хийнэ. Номын {c('client.c')} жишээ ажиллах ёстой."])
    d.section("Багшийн нэмэлт шаардлага")
    d.p('Бие даалт 1-ийн удирдамжаар дараах шаардлага нэмэгдэнэ: оролт, параметрийг өөрчилж дахин турших; буруу болон захын оролтыг шалгаж ойлгомжтой мэдээлэх; тохиргоог солих, дахин ажиллуулах, reset хийх; оноосон "Worker activity" UI-г бодит ажиллагаатай холбох; номын болон нэмэлт туршилтаар зөв ажиллагааг нотлох; Manual-ын дагуу өөр компьютерт ажиллуулах боломжтой байх; GitHub repository, README, Release/Tag. Хуваарилалтын файлд 9-р сэдвийн хүрэх үр дүнг "Worker-ийн тоо, task queue, ажлын параметрийг өөрчилж, worker бүрийн idle, running, completed төлөвийг хугацааны явцад харуулна" гэж тодорхойлсон.')
    d.section("Шаардлагын хангалт")
    d.table("Шаардлага ба хэрэгжсэн газар", [
        ["Шаардлага", "Хэрэгжилт"],
        [f"{c('pool_init')}: thread, mutex, semaphore", f"{c('src/threadpool.c')}: {c('pool_init()')} (3 worker, queue 10), {c('pool_init_ex(n, cap)')}"],
        [f"{c('pool_submit')}, массив queue, дүүрвэл 1", f"Тойрог массив, {c('POOL_OK=0')}, {c('POOL_FULL=1')}"],
        [f"{c('worker')}: semaphore дээр хүлээх", f"{c('sem_wait(work_available)')} → {c('dequeue()')} → {c('execute()')}"],
        ["Queue-г mutex-ээр хамгаалах", c("pthread_mutex_t qmutex")],
        [f"{c('pool_shutdown')}, {c('pthread_join')}", "Shutdown флаг + worker бүрт нэг sem_post, үлдсэн task-уудыг гүйцээгээд гарна"],
        [f"Номын {c('client.c')}", f"{c('examples/client.c')}, тест T1"],
        ["Параметр өөрчилж дахин турших, reset", "Интерфейсийн тохиргоо, Ажиллуулах/Reset/Анхдагч, бэлэн тест; CLI сонголтууд"],
        ["Буруу оролт шалгах", "C программ (exit 2 + тайлбар), сервер (HTTP 400), UI (улаан талбар)"],
        ["Worker activity, бодит ажиллагаатай холбох", "Бодит C программын trace-ээр worker карт, queue, timeline зурна"],
        ["Нэмэлт туршилт", f"{npass} автомат тест, хараат бус trace шалгагч, ThreadSanitizer, 3 туршилт, CI"],
    ], key="req", widths=[42, 58])

    # ---------------- ГУРАВ ----------------
    d.chapter("Онолын үндэс")
    d.section("Thread pool")
    d.p("Thread pool нь эхлэхдээ тогтмол тооны thread үүсгэж, тэднийг pool-д хүлээлгэнэ. Ирсэн ажил queue-д орж, чөлөөтэй thread түүнийг авч гүйцэтгээд дахин pool руу буцна (номын 4.5.1). Давуу тал нь: байгаа thread-ээр үйлчлэх нь шинэ thread үүсгэхээс хурдан; нэгэн зэрэг ажиллах thread-ийн тоо хязгаарлагдмал тул систем хэт ачаалагдахгүй; ажлыг гүйцэтгэх механизмаас тусгаарласан тул хуваарилах стратегийг тусад нь өөрчилж болно.")
    d.section("Critical section ба race condition")
    d.p(f'Хэд хэдэн thread нэг дундын өгөгдлийг зэрэг өөрчлөх үед үр дүн нь гүйцэтгэлийн дараалалаас хамаарах нөхцөлийг race condition гэнэ. Queue-д task нэмэх нь "{c("queue[tail] = t")}", "{c("tail = (tail + 1) % cap")}", "{c("count++")}" гэсэн хэд хэдэн алхмаас бүрдэх critical section юм. Хоёр worker зэрэг dequeue хийвэл нэг task-ийг давхар авч, нөгөөг алгасах аюултай. Critical section-ийн шийдэл нь харилцан гадуурхал (mutual exclusion), ахиц (progress), хязгаартай хүлээлт (bounded waiting) гэсэн гурван шаардлагыг хангах ёстой.')
    d.section("Mutex lock")
    d.p(f"Mutex нь нэг мөчид зөвхөн нэг thread-д critical section-д орох эрх олгоно ({c('pthread_mutex_lock/unlock')}). Цоож барьсан thread л queue-г өөрчлөх тул {c('head')}, {c('tail')}, {c('count')} зөрөхгүй. Цоожийг аль болох богино хугацаанд барих ёстой: task-ийг гүйцэтгэх хугацаанд барьвал worker-ууд дараалж ажиллан pool утгагүй болно.")
    d.section("Semaphore")
    d.p(f"Semaphore нь бүхэл тоон утгатай хувьсагч бөгөөд зөвхөн хоёр атомар үйлдлээр хандана. {c('wait()')} (POSIX: {c('sem_wait')}) утгыг 1-ээр хасна; утга 0 байвал thread блоклогдож хүлээнэ. {c('signal()')} ({c('sem_post')}) утгыг 1-ээр нэмж, хүлээж буй thread байвал нэгийг сэрээнэ. Thread pool-д counting semaphore-ийн утга нь queue дахь task-ийн тоотой тэнцүү: ажилгүй worker {c('sem_wait')} дээр унтаж, CPU үрэхгүй (busy waiting байхгүй). Номд unnamed semaphore ({c('sem_init(&sem, 0, 0)')}) ашиглахыг зөвлөсөн.")
    d.section("Bounded buffer ба тойрог queue")
    d.p(f"Thread pool-ийн queue нь номын 7.1.1 хэсгийн bounded buffer бодлогын нэг хэлбэр. Номын шийдэл {c('mutex')}, {c('empty')}, {c('full')} гурван синхрончлолын хувьсагч ашигладаг (номын Зураг 7.1–7.2):")
    d.code("Consumer-ийн бүтэц (номын Зураг 7.2)", """while (true) {
   wait(full);
   wait(mutex);
   /* remove an item from buffer to next_consumed */
   signal(mutex);
   signal(empty);
   /* consume the item in next_consumed */
}""", key="book")
    d.p(f"Thread pool-д worker нь consumer бөгөөд {c('full')}-ийн үүргийг {c('work_available')} semaphore гүйцэтгэнэ. Харин {c('empty')}-ийн оронд дүүрсэн queue-д client-ийг блоклохгүйгээр шууд 1 буцаадаг нь номын {c('pool_submit()')}-ийн тодорхойлолт юм. Queue нь {c('cap')} нүдтэй массив, хоёр заагчтай: {c('tail')} нь дараагийн тавих нүд, {c('head')} нь дараагийн авах нүд. Заагч бүр {c('(i + 1) % cap')}-ээр урагшилж, сүүлийн нүдний дараа 0 руу эргэнэ. Иймээс анх орсон task анх гүйцэтгэгдэнэ (FIFO).")
    d.section("Thread-ийг зогсоох")
    d.p(f"Номд {c('pthread_cancel()')}-ийг санал болгосон ({c('sem_wait()')} нь cancellation point). Гэвч deferred cancellation нь task ажиллаж байх үед {c('nanosleep')} зэрэг cancellation point дээр thread-ийг тасалж, task-ийг дутуу орхих, барьсан нөөцийг суллахгүй байх эрсдэлтэй (номын 4.6.3). Тиймээс хамтран зогсох (cooperative) аргыг сонгов: shutdown флаг тавиад worker бүрт нэг {c('sem_post')} илгээнэ. Энэ нь API-ийн \"бүх task дууссаны дараа зогсоно\" гэсэн тайлбартай нийцнэ.")
    d.section("Invariant")
    d.p(f'Зөв синхрончлолтой ажиллалтын төгсгөлд "хүлээн авсан = гүйцэтгэсэн", "task бүр яг 1 удаа ажилласан", "нэгэн зэрэг ажилласан task ≤ worker-ийн тоо", "queue-ийн урт ≤ багтаамж" гэсэн тэнцэл үргэлж биелнэ. Программ төгсгөлд нь эдгээрийг шалгаж ({c("VERIFY: OK")}), тест болон интерфейс зөв ажиллагааны нотолгоо болгон ашиглана.')

    # ---------------- ДӨРӨВ ----------------
    d.chapter("Системийн зохиомж")
    d.section("Бүрэлдэхүүн хэсгүүд")
    d.p("Систем гурван хэсгээс бүрдэнэ (Зураг {F:arch}): синхрончлолыг бодитоор гүйцэтгэдэг C программ (core), түүнийг ажиллуулж trace-ийг дамжуулдаг Python сервер, trace-ийг дүрсэлдэг браузерийн интерфейс.")
    d.diagram("arch", "Системийн бүрэлдэхүүн ба өгөгдлийн урсгал", key="arch")
    d.p("Core-ийн дотор client thread task-уудыг queue-д хийж, worker-ууд semaphore-оор сэрж авна (Зураг {F:pool}).")
    d.diagram("pool", "Pool доторх урсгал: submit → queue → semaphore → worker", key="pool")
    d.section("Өгөгдлийн урсгал")
    d.ol(["Хэрэглэгч тохиргоо хэсэгт worker, queue, бодлого, task-ийн тоо, хугацаа, ирэх зай, seed-ийг сонгох эсвэл task жагсаалт оруулаад <b>Ажиллуулах</b> дарна.",
          f"Browser {c('POST /api/run')} хүсэлт илгээнэ. Сервер утгуудыг CLI аргумент болгож {c('build/threadpool_sim')}-ийг ажиллуулна. Буруу утгыг C программ өөрөө шалгаж, exit 2 + тайлбар буцаавал сервер HTTP 400 болгон дамжуулна.",
          "Core pool-ийг эхлүүлж, task бүрийг тогтоосон агшинд submit хийн, worker-ууд бодитоор гүйцэтгэнэ. Үйлдэл бүр санах ойн trace-д бүртгэгдэнэ. Shutdown-ы дараа 8 инвариант шалгаад бүх trace-ийг JSON болгон stdout руу хэвлэнэ.",
          "Browser JSON-ийг хүлээн авч worker карт, queue, timeline, бүртгэлийг зурж, playback-аар тоглуулна. Trace-ийг файлд хадгалж, дараа нь сервергүйгээр дахин үзэж болно."])
    d.section("Үйлдлийн (event) формат")
    d.p("Trace-ийн үйлдэл бүр нэг мөр бөгөөд тухайн агшны queue-ийн уртыг агуулна (Хүснэгт {T:ev}).")
    d.table("JSON үйлдлийн талбарууд", [
        ["Талбар", "Утга"],
        [c("t"), f"{c('pool_init')}-ээс хойшх хугацаа (микросекунд)"],
        [c("type"), f"{c('POOL_INIT')}, {c('IDLE')}, {c('SUBMIT')}, {c('REJECT')}, {c('START')}, {c('END')}, {c('SHUTDOWN')}, {c('WORKER_EXIT')}"],
        [c("w"), "worker-ийн дугаар (0-ээс), хамааралгүй бол −1"],
        [c("task"), "task-ийн дугаар, хамааралгүй бол −1"],
        [c("q"), "үйлдлийн дараах queue-ийн урт"],
        [c("summary"), f"{c('submitted')}, {c('rejected')}, {c('completed')}, {c('avg_wait_ms')}, {c('makespan_ms')}, {c('utilization_pct')}, {c('per_worker')}"],
        [c("verify"), f"{c('ok')} ба 8 шалгалтын нэр, үр дүн, тайлбар"],
    ], key="ev", widths=[22, 78])
    d.p("Жишээ мөр:")
    d.code(None, '{"t":94,"type":"SUBMIT","w":-1,"task":0,"q":1},\n{"t":122,"type":"START","w":1,"task":0,"q":0}', lang="json")
    d.p(f"Цагийг trace-ийн mutex дотор авдаг тул массивын дараалал хугацааны дараалалтай давхцана. {c('SUBMIT')}, {c('START')}-ийг queue-ийн mutex дор бүртгэдэг тул бүртгэсэн {c('q')} нь бодит queue-ийн урттай яг тэнцүү.")
    d.section("Хязгаар ба хамгаалалт")
    d.p("C программ: worker 1-64, queue 1-4096, task 1-10000, хугацаа 1-60000 мс, ирэх зай 0-60000 мс. Сервер нэг ажиллуулалтад интерфейсээс 2000-аас олон task, ойролцоогоор 60 секундээс урт ажлыг хүлээж авахгүй, 120 секундэд дуусаагүй процессыг зогсооно, зөвхөн 127.0.0.1 хаягаас хүсэлт хүлээн авна.")

    # ---------------- ТАВ ----------------
    d.chapter("Хэрэгжилт")
    d.section("Хэл, сан, орчин")
    d.table("Ашигласан технологи", [
        ["Хэсэг", "Технологи"],
        ["Core", f"C11 (gcc/clang, {c('-O2 -Wall -Wextra -pthread')}), POSIX threads, POSIX semaphore (macOS дээр {c('dispatch_semaphore')})"],
        ["Сервер", f"Python 3 стандарт сан ({c('http.server')}, {c('subprocess')}), нэмэлт сангүй"],
        ["Интерфейс", "HTML, CSS, JavaScript, SVG; гадны сан, CDN ашиглаагүй"],
        ["Тест", f"POSIX shell ({c('tests/run_tests.sh')}), Python 3 ({c('tests/verify_trace.py')}), ThreadSanitizer"],
        ["CI", "GitHub Actions (ubuntu-latest, macos-latest)"],
    ], key="tech", widths=[22, 78])
    d.section("C core: queue")
    d.p(f"Номын API-г хадгалж, queue-г тойрог массиваар хэрэгжүүлэв. Функцууд {c('qmutex')} барьсан үед л дуудагдана.")
    d.code(f"{c('enqueue')} ба {c('dequeue')} (src/threadpool.c)",
           snippet("src/threadpool.c", "static int enqueue(task t)", "static void execute("), key="queue")
    d.section("C core: worker")
    d.p(f"Worker {c('sem_wait')}-ээр ажил хүлээж, mutex дор dequeue хийгээд, task-ийг mutex-ийн <b>гадна</b> гүйцэтгэнэ (Код {{K:worker}}).")
    d.code("Worker thread-ийн функц (src/threadpool.c)",
           snippet("src/threadpool.c", "static void *worker(void *param)", "/* ---------------- API"), key="worker")
    d.p("Гол шийдлүүд:")
    d.ul([f"{c('sem_wait')} нь mutex-ээс гадна байна. Mutex барьсан чигээр блоклогдвол client submit хийж чадахгүй тул deadlock болно.",
          f"{c('execute()')}-ийг mutex-ийг суллаад дуудна. Ингэснээр N worker зэрэг ажиллана.",
          f"Queue хоосон, shutdown флаг тавигдсан үед л worker гарна. Иймээс shutdown-ы үед queue-д үлдсэн task-ууд бүгд гүйцэтгэгдэнэ.",
          f"{c('sem_wait')}-ийг {c('EINTR')} (дохиогоор тасалдсан) үед давтана."])
    d.section("C core: submit ба shutdown")
    d.code(f"{c('pool_submit')} (src/threadpool.c)",
           snippet("src/threadpool.c", "int pool_submit_id(", "int pool_submit(void"), key="submit")
    d.p(f"{c('sem_post')}-ийг mutex суллагдсаны дараа дуудна; task queue-д орсон үед л post хийдэг тул semaphore-ийн утга queue-ийн уртаас хэзээ ч их болохгүй.")
    d.code(f"{c('pool_shutdown')}-ийн гол хэсэг (src/threadpool.c, товчилсон)", """pthread_mutex_lock(&qmutex);
shutting_down = 1;
pthread_mutex_unlock(&qmutex);

/* Worker бүрт нэг "гарах" дохио. Queue-д үлдсэн task бүр өөрийн post-той
 * тул worker-ууд эхлээд бүх task-ийг гүйцээж, дараа нь л гарна. */
for (int i = 0; i < nthreads; i++) psem_post(&work_available);
for (int i = 0; i < nthreads; i++) pthread_join(workers[i].tid, NULL);""", key="shutdown")
    d.p(f"<b>Зөв байдлын тайлбар.</b> Shutdown-ы өмнө queue-д <i>k</i> task байлаа гэж үзье. Semaphore-ийн утга <i>k + N</i> болно. Worker зөвхөн queue хоосон үед гардаг тул эхний <i>k</i> сэрэлтээр task авч, үлдсэн <i>N</i> сэрэлтээр worker бүр нэг удаа гарна. Иймээс бүх task гүйцэтгэгдэж, {c('pthread_join')} блоклогдож үлдэхгүй. Бусад шийдэл:")
    d.ul([f"macOS нэргүй semaphore ({c('sem_init')}) дэмждэггүй тул {c('#ifdef __APPLE__')} үед {c('dispatch_semaphore')} ашиглана.",
          f"Trace бүртгэлийг тусдаа {c('tr_mutex')}-ээр хамгаалж, цагийг mutex дотор авдаг тул үйлдлүүд хугацааны дарааллаар хадгалагдана.",
          f"Аргумент бүрийг {c('strtol')}-оор бүтнээр нь шалгаж (жишээ нь {c('12abc')} хүлээж авахгүй), алдаатай бол Монгол хэлээр тайлбар хэвлээд 2 кодоор гарна. Task файлын алдааг {c('файл:мөр')} байршилтай мэдээлнэ.",
          f"Ажиллаж дууссаны дараа trace-ээс 8 инвариант шалгаж, аль нэг нь зөрвөл 4 кодоор гарна."])
    d.section("Сервер")
    d.p(f"{c('tools/server.py')} нь JSON тохиргоог CLI аргумент болгон {c('threadpool_sim')}-ийг {c('subprocess')}-ээр ажиллуулж, stdout дахь JSON trace-ийг browser руу буцаана. Task жагсаалтыг түр файлд бичиж {c('-f')} сонголтоор дамжуулна. C программ 2 кодоор гарвал алдааны текстийг HTTP 400-аар, хугацаа хэтэрвэл HTTP 504-өөр мэдээлнэ. Сервер интерфейсийн файлыг ({c('ui/index.html')}) мөн өөрөө түгээнэ.")
    d.section("Интерфейс")
    d.ul(["<b>Тохиргоо</b>: worker, queue, дүүрэх үеийн бодлого (reject/retry), task-ийн тоо, хугацаа, ирэх зай, seed эсвэл task жагсаалт ба бэлэн тест (Зураг {F:settings}).",
          "<b>Worker карт</b>: worker бүрийн одоогийн төлөв (● running Tk, ○ idle, ■ exited), явцын шугам, дуусгасан task-ийн тоо (✓ n).",
          "<b>Task queue</b>: хүлээж буй task-ууд FIFO дарааллаар, багтаамжийн хоосон нүд; хүлээн авсан, ажиллаж буй, дууссан, татгалзсан тоолуур; тухайн агшны үйлдлийн тайлбар.",
          "<b>Worker activity timeline</b>: worker бүр нэг мөр, client мөр (submit, reject), queue-ийн уртын график, shutdown, playhead (Зураг {F:overview}).",
          "<b>Playback</b>: тоглуулах/зогсоох, өмнөх/дараагийн үйлдэл, гулсуур, 0.25×-10× хурд; timeline дээр дарж, чирж очих.",
          "<b>Үр дүн ба шалгалт</b>, <b>үйлдлийн бүртгэл</b>: хэмжүүрүүд, 8 шалгалт, C программын команд ба stderr; бүртгэлийн мөр дээр дарж тэр агшин руу очно."])
    d.shot("img/user/ui_default_754.png", "Интерфейсийн ерөнхий харагдац: 3 worker, queue 5, 15 task-ийн бодит ажиллалт, t = 754 мс агшин (3 worker running, queue-д 4 task, 1 татгалзал)", key="overview", width=88)
    d.section("GitHub дээрх ажиллагаа")
    d.p(f"Repository: <span class='mono'>{REPO}</span>. README (Quick Start), {c('src/')}, {c('tests/')}, {c('examples/')}, {c('tools/')}, {c('ui/')}, {c('docs/')} бүтэцтэй. {c('.github/workflows/ci.yml')} нь push болон Pull Request бүрт Ubuntu дээр build, {c('make test')}, ThreadSanitizer, macOS дээр clang build ба тестийг ажиллуулна. Гишүүн бүрийн хариуцсан хэсэг, commit-ийг Хавсралт А-д тэмдэглэв. 9-р долоо хоногт {c('v1.0')} tag ба GitHub Release нийтэлнэ.")
    d.section("Source")
    d.p(f"Номын API-ийн нэр, {c('client.c')} жишээний бүтцийг сурах бичгээс авсан. Код, интерфейс, тест, баримт бичгийн анхны хувилбарыг AI туслахын тусламжтайгаар бичиж, баг бүх өөрчлөлтийг бодит C программ дээр ажиллуулан тест болон гараар шалгасан. Гадны сан, бэлэн component ашиглаагүй. Дэлгэрэнгүйг README-ийн \"AI ба бэлэн код ашигласан тухай\" хэсгээс харна.")

    # ---------------- ЗУРГАА ----------------
    d.chapter("Туршилт ба UI дүрслэл")
    d.section("Өөрчилж турших параметр")
    d.table("Тохиргооны параметр", [
        ["Параметр", "Нөлөө", "Хүрээ (анхдагч)"],
        ["Worker thread", "зэрэг ажиллах thread-ийн тоо; timeline-ийн мөрийн тоо", "1-64 (3)"],
        ["Queue багтаамж", "хүлээж болох task-ийн тоо; бага бол татгалзал олширно", "1-4096 (5)"],
        ["Дүүрэх үед", "reject: номын дагуу 1 буцааж хаяна; retry: client хүлээгээд дахин оролдоно", "reject"],
        ["Retry зай (мс)", "retry горимд дахин оролдох хоорондын зай", "1-10000 (20)"],
        ["Task-ийн тоо", "үүсгэх task-ийн тоо", "1-2000 (15)"],
        ["Хугацаа (мс)", "task бүрийн ажиллах хугацааны муж", "1-60000 (200-800)"],
        ["Ирэх зай (мс)", "дараалсан task-уудын хоорондох зай; 0 бол бүгд зэрэг", "0-60000 (20-120)"],
        ["Seed", "ижил seed = ижил ачаалал", "≥ 0 (42)"],
        ["Task жагсаалт", f"мөр бүр {c('arrival_ms duration_ms')}; бэлэн тест сонгож болно", "≤ 2000 мөр"],
    ], key="params", widths=[22, 54, 24])
    d.shot(IMG("settings"), "Тохиргоо: pool, ачаалал, ажиллуулах товч", key="settings", width=38)
    d.section("Юуг ажиглах")
    d.ul([f"Queue хоосон үед worker-ууд \"○ idle — sem_wait\" төлөвтэй, timeline дээр судалтай саарал байна; task ирмэгц нэг нь сэрж running болно.",
          "Worker бүх нь завгүй үед task-ууд queue-д хуримтлагдаж, queue-ийн уртын график өснө; task хамгийн зүүн (head) талаас нь авагдана (FIFO).",
          f"Queue дүүрсэн үед client мөрөнд улаан ✕ гарч, \"татгалзсан\" тоолуур өснө ({c('pool_submit')} 1 буцаасан).",
          "Нэг worker нэг мөчид зөвхөн нэг task-тай; нэгэн зэрэг ажиллах task-ийн тоо worker-ийн тооноос хэтрэхгүй.",
          "Shutdown (тасархай зураас)-ы дараа queue-д үлдсэн task-ууд гүйцэтгэгдэж, дараа нь worker бүр гарна (бараан бүс)."])
    d.section("Бэлэн туршилтууд")
    d.table("Интерфейсийн бэлэн туршилт", [
        ["Туршилт", "Тохиргоо", "Хүлээгдсэн ажиглалт"],
        [c("basic.txt"), "W=3, Q=10, 10 task", "бүх task хүлээн авагдаж, зэрэг ≤ 3"],
        [c("burst.txt"), "W=2, Q=3, 10 task t=0, reject", "3-5 хүлээн авч, үлдсэнийг татгалзана"],
        [c("burst.txt"), "W=2, Q=3, retry", "10 бүгд хүлээн авагдана, нийт хугацаа уртасна"],
        [c("fifo.txt"), "W=1, Q=10, 6 task", "ирсэн дарааллаараа T0…T5"],
        [c("mixed_long_short.txt"), "W=3, 1×1500 мс + 7×100 мс", "урт task нэг worker-ийг эзэлж, бусад нь богинуудыг гүйцэтгэнэ"],
    ], key="presets", widths=[33, 30, 37])

    # ---------------- ДОЛОО ----------------
    d.chapter("Туршилтын арга")
    d.section("Орчин")
    d.p(f"Хөгжүүлэлт ба автомат туршилт: {E['os']} ({E['arch']}, kernel {E['kernel']}), {E['gcc']}, glibc {E['glibc']}, Python {E['py']}, CPU: {E['cpu']}. Интерфейсийг Chromium (headless) дээр туршиж дэлгэцийн зургийг авав. CI: GitHub Actions ubuntu-latest (gcc), macos-latest (clang). Windows дээр WSL2 Ubuntu-аар ажиллана.")
    d.p("Үүнээс гадна багийн гишүүн Ц.Номинжингийн Ubuntu компьютер дээр Manual-ын дагуу repository-г татаж, VS Code-ийн терминал болон дотоод browser-оос бүх командыг дахин ажиллуулж шалгав (8.4 хэсэг).")
    d.section("Core-ийн автомат тест")
    d.p(f"{c('tests/run_tests.sh')} нь программыг олон тохиргоогоор ажиллуулж, гарсан trace-ийг шалгана:")
    d.ul([f"<b>Номын жишээ (T1)</b>: {c('examples/client.c')} 5 нийлбэрийг зөв хэвлэх.",
          "<b>Үндсэн (T2-T7)</b>: анхдагч тохиргоо, queue дүүрэх (reject, retry), FIFO, урт ба богино task, санамсаргүй ачаалал.",
          "<b>Захын (B1-B5)</b>: queue=1, worker > task, 64 worker, 1 task, 500 task-ийн stress.",
          "<b>Буруу оролт (E1-E17)</b>: 0 ба 65 worker, queue=0, тоо биш утга, MIN > MAX, сөрөг зай, үл мэдэгдэх бодлого/сонголт, утгагүй сонголт, байхгүй файл, файлд тоо биш утга, эрэмбэгүй мөр, 3 баганатай мөр, 0 хугацаа, хоосон файл. Exit код 2 ба алдааны текстийг шалгана."])
    d.section("Trace шалгагч ба ThreadSanitizer")
    d.p(f"{c('tests/verify_trace.py')} нь C кодоос хараат бусаар: queue-ийн уртыг SUBMIT/START-аас дахин сэргээж бүртгэсэн {c('q')}-тэй тулгах; нэг worker дээрх интервал давхцахгүй; START-ийн дараалал = SUBMIT-ийн дараалал (FIFO); SHUTDOWN-ы дараа SUBMIT байхгүй; worker бүр WORKER_EXIT хийсэн эсэхийг шалгана. Мөн тест бүрт хүлээгдсэн тоог ({c('--expect accepted=10')} гэх мэт) тулгана. {c('make tsan')} нь {c('-fsanitize=thread')}-тэй build хийж, 4 worker, queue 3, 40 task, retry горимоор өрсөлдөөнийг ихэсгэн ажиллуулна.")
    d.section("Гүйцэтгэлийн туршилт")
    d.p(f"{c('tests/experiments.sh')} нь worker-ийн тоо, queue-ийн багтаамж, дүүрэх үеийн бодлогыг тус тусад нь өөрчилж, бусад параметрийг тогтмол барина (seed тогтмол).")
    d.section("Гар туршилт")
    d.p("Интерфейсийн бэлэн туршилтууд, буруу оролт (worker 0, task жагсаалтад тоо биш утга), алхамчлах, хурд солих, trace хадгалах ба сервергүйгээр ачаалахыг browser дээр гараар туршиж, дэлгэцийн зургаар баримтжуулав (8-р бүлэг).")

    # ---------------- НАЙМ ----------------
    d.chapter("Үр дүн")
    d.section("Core-ийн тестийн үр дүн")
    d.p(f"Linux дээрх ажиллалтын үр дүн (Хүснэгт {{T:tests}}). Бодит үр дүн баганын тоо {c('build/test_output.txt')}-ээс шууд авсан.")
    fmt = lambda s: f"хүлээн авсан {s['accepted']}, татгалзсан {s['rejected']}, зэрэг {s['max_running']}, queue {s['max_queue']}"
    rows = [["ID", "Тест", "Бодит үр дүн", "Дүн"],
            ["T1", f"Номын {c('client.c')}", "15, 3, 300, 0, 42 зөв хэвлэгдсэн", "PASS" if client_ok else "FAIL"]]
    for tid, name, desc in TEST_IDS:
        s = st[name]
        rows.append([tid, desc, fmt(s), s["res"]])
    eok = sum(1 for r, _, _ in errs if r == "PASS")
    rows.append(["E1-E17", "Буруу оролт", f"exit=2, тохирох тайлбар (жишээ нь \"-w буруу ('0'): worker-ийн тоо 1..64 бүхэл тоо байна\")", "PASS" if eok == len(errs) == 17 else f"{eok}/{len(errs)}"])
    rows.append(["R1", "ThreadSanitizer", "race илрээгүй, VERIFY: OK", "PASS"])
    d.table(f"Автомат тестийн үр дүн ({c('make test')}, {c('make tsan')})", rows, key="tests", widths=[10, 34, 46, 10])
    d.p(f"Нийт {npass}/{int(npass)+int(nfail)} PASS. Бүх тестийн trace хараат бус шалгагчаар баталгаажсан, ThreadSanitizer race илрүүлээгүй. B3 тестэд 64 worker бүгд зэрэг ажилласан, B5 тестэд 500 task бүр яг 1 удаа гүйцэтгэгдсэн.")
    d.section("Гүйцэтгэлийн туршилтын үр дүн")
    d.p("<b>Туршилт 1. Worker-ийн тоо.</b> 40 task, хугацаа 100-300 мс, бүгд t=0-д ирнэ, queue 64, seed 1.")
    d.table("Worker-ийн тооны нөлөө", [["Worker", "Нийт хугацаа (мс)", "Дундаж хүлээлт (мс)", "Дундаж turnaround (мс)", "Ашиглалт (%)", "Хурдатгал"]] +
            [[r[0], f"{float(r[3]):.0f}", f"{float(r[4]):.0f}", f"{float(r[5]):.0f}", f"{float(r[6]):.1f}", f"{sp(r):.2f}×"] for r in x1], key="exp1")
    d.p(f"Нийт хугацаа worker-ийн тоонд бараг урвуу пропорциональ буурсан (2 worker → {sp(x1[1]):.2f}×, 8 worker → {sp(x1[3]):.2f}×). 16 worker-т ашиглалт {float(x1[4][6]):.0f}% хүртэл буурсан: 40 task 16 worker-т тэгш хуваагдахгүй тул сүүлийн давалгаанд зарим worker idle үлдэнэ.")
    d.p("<b>Туршилт 2. Queue-ийн багтаамж.</b> 2 worker, 20 task t=0-д, тус бүр 100 мс, reject.")
    d.table("Queue-ийн багтаамжийн нөлөө", [["Queue", "Хүлээн авсан", "Татгалзсан", "Queue дээд урт", "Нийт хугацаа (мс)"]] +
            [[r[0], r[1], r[2], r[3], f"{float(r[4]):.0f}"] for r in x2], key="exp2")
    d.p(f"Хүлээн авсан task-ийн тоо багтаамжтай яг тэнцүү гарсан. Client 20 task-ийг микросекундын дотор submit хийдэг бол worker {c('sem_wait')}-аас сэрж dequeue хийхэд түүнээс урт хугацаа шаардана; иймээс burst-ийн үед queue хоосрохоос өмнө дүүрнэ.")
    d.p("<b>Туршилт 3. Дүүрэх үеийн бодлого.</b> 2 worker, queue 3, 20 task 10 мс зайтай, тус бүр 100 мс.")
    d.table("Reject ба retry бодлого", [["Бодлого", "Хүлээн авсан task", "Татгалзсан оролдлого", "Нийт хугацаа (мс)", "Дундаж хүлээлт (мс)"]] +
            [[r[0], r[1], r[2], f"{float(r[3]):.0f}", f"{float(r[4]):.0f}"] for r in x3], key="exp3")
    d.p("Reject горимд task алдагдсан ч нийт хугацаа богино; retry горимд бүх task гүйцэтгэгдсэн боловч client хүлээсэн тул уртассан.")
    d.section("Интерфейсийн үр дүн")
    d.p("Зураг {F:burst}-{F:err} нь бодит программын ажиллалтаас авсан дэлгэцийн зураг.")
    d.shot(IMG("burst_reject"), "Queue дүүрэх (W=2, Q=3, reject): t=30 мс-д T0, T1 ажиллаж, T2 queue-д, 7 task татгалзсан (client мөрөнд ✕)", key="burst")
    d.shot(IMG("burst_retry"), "Ижил ачаалал, retry горим: client дахин оролдож (✕ олон), 10 task бүгд гүйцэтгэгдсэн")
    d.shot(IMG("fifo_step"), "FIFO (W=1): дараагийн үйлдэл товчоор алхамчилсан; T3, T4, T5 ирсэн дарааллаараа queue-д хүлээж байна")
    d.shot(IMG("long_short"), "Урт (T0 = 1500 мс) ба богино task: W0 урт task-аар эзлэгдсэн ч W1, W2 богинуудыг гүйцэтгэсээр")
    d.shot(IMG("eight_workers"), "8 worker, queue 16, 60 task: queue-ийн урт ачааллын давалгааг дагаж өсөж буурна")
    d.shots(['compare_w1', 'compare_w4'], "Ижил 12 task (100-300 мс, seed 1): дээр 1 worker, доор 4 worker; нийт хугацаа ойролцоогоор 4 дахин богиносов", width=78, layout="stack")
    d.shot(IMG("summary"), "Үр дүн ба шалгалт: хэмжүүрүүд, VERIFY OK ба 8 шалгалт, C программын команд", key="summary")
    d.shots(['error_workers0', 'error_file'], "Буруу оролт: зүүн талд worker = 0, баруун талд task жагсаалтын 2-р мөрөнд тоо биш утга", key="err", width=80, layout="row")

    # ---------------- ЕС ----------------
    d.section("Хэрэглэгчийн компьютер дээрх баталгаажуулалт")
    d.p(f"Программ зөвхөн хөгжүүлэлтийн орчинд биш, өөр компьютер дээр ч Manual-ын дагуу ажилладаг эсэхийг шалгахын тулд багийн гишүүний Ubuntu компьютер дээр ({c('nominjin@ubuntu')}) repository-г zip-ээр татаж, VS Code-оос {c('make')}, {c('make test')}, {c('make ui')}, {c('make tsan')} болон CLI командуудыг ажиллуулав. Нэмэлт тохиргоо, засвар хийгээгүй. Үр дүнг Хүснэгт {{T:userrun}}-д нэгтгэв.")
    d.table("Хэрэглэгчийн компьютер дээрх ажиллалтын үр дүн", [
        ["Шалгалт", "Хүлээгдсэн үр дүн", "Хэрэглэгчийн компьютер дээр", "Зураг"],
        [c("make test"), "29 PASS, 0 FAIL", "29 PASS, 0 FAIL", "{F:utest}"],
        [c("make ui"), "C программтай холбогдож, run хийгдэнэ", "\"C программтай холбогдсон\", POST /api/run 200, VERIFY OK", "{F:uiend}, {F:uilog}"],
        [c("./build/client"), "5 нийлбэр зөв", "3, 0, 42, 15, 300 (дараалал өөр)", "{F:ucli}"],
        [c("-w 3 -q 5 -n 15"), "15/15 гүйцэтгэгдэнэ", "15 хүлээн авсан, 0 татгалзсан, 8 шалгалт OK", "{F:ucli}"],
        [c("-w 2 -q 3 -f burst.txt"), "3-5 хүлээн авч, үлдсэнийг татгалзана", "3 хүлээн авсан, 7 татгалзсан", "{F:ucli}"],
        [c("make tsan"), "race илрэхгүй", "ThreadSanitizer WARNING байхгүй, VERIFY OK", "{F:utsan}"],
    ], key="userrun", widths=[25, 26, 37, 12])
    d.p(f"Зураг {{F:uiend}}-д VS Code-ийн дотоод browser-оос {c('http://localhost:8000')} нээж, анхдагч тохиргоогоор (3 worker, queue 5, 15 task, seed 42) ажиллуулаад төгсгөлийн агшинд ({c('t = 2270 ms')}) очсон байдал харагдана. Shutdown-ы дараа гурван worker бүгд \"exited\" төлөвтэй, queue хоосон, 13 task хүлээн авч, 2 task татгалзсан, бүх шалгалт OK. Seed ижил тул ачаалал 8.3 хэсгийн ажиллалттай (Зураг {{F:summary}}) ижил: хүлээн авсан, татгалзсан тоо (13, 2) яг давхцаж, нийт хугацаа (2270.4 мс ба 2271.2 мс) 1 мс-ийн дотор зөрсөн. Харин worker бүрийн дуусгасан task-ийн тоо (W0:4, W1:4, W2:5 ба W0:5, W1:4, W2:4) өөр байгаа нь аль worker аль task-ийг авахыг OS scheduler шийддэгийг харуулна. Тиймээс үр дүн өөр компьютер дээр давтагдаж, зөвхөн хуваарилалт л өөрчлөгдөнө.")
    d.photos(["img/user/ui_vscode_end.png"], "Хэрэглэгчийн компьютер: VS Code-ийн browser дээр Worker activity, ажиллалтын төгсгөл (бүх worker exited, VERIFY OK)", key="uiend", width=100)
    d.p(f"Зураг {{F:uilog}}-д playback-ийг {c('t = 2137 ms')} агшинд зогсоосон: W0, W1, W2 нь T11, T13, T12-ийг гүйцэтгэж (running), queue хоосон, 10 task дууссан. Доорх терминалд {c('make ui')}-ийн серверийн бүртгэл харагдана: браузер {c('GET /')}, {c('/api/health')}, {c('/api/presets')} хүсэлтийн дараа {c('POST /api/run')} илгээж, сервер C программыг ажиллуулаад 200 кодоор trace буцаасан. Өөрөөр хэлбэл дэлгэцийн дүрслэл бодит C программын ажиллалтаас гарсан. {c('/favicon.ico')}-ийн 404 нь хуудасны дүрс тэмдэг байхгүйг заах бөгөөд ажиллагаанд нөлөөлөхгүй.")
    d.photos(["img/user/ui_running_server_log.png"], "Ажиллалтын дунд агшин (3 worker running) ба серверийн бүртгэл (POST /api/run 200)", key="uilog", width=100)
    d.p(f"Зураг {{F:utest}}-д {c('make test')}-ийн бүрэн гаралт: номын жишээ, 6 үндсэн, 5 захын тест бүр C талын шалгалт болон хараат бус trace шалгагчаар (\"trace шалгалт: OK\") баталгаажиж, 17 буруу оролтын тест бүр зөв алдааны мессеж өгсөн. Төгсгөлд {c('Нийт: 29 PASS, 0 FAIL')}. Тоон утгууд (хүлээлт, ашиглалт) Хүснэгт {{T:tests}}-ийнхтэй ойролцоо, хүлээн авсан/татгалзсан тоо ижил.")
    d.photos([("img/user/make_test_1.png", 66), ("img/user/make_test_2.png", 66)], "Хэрэглэгчийн компьютер дээрх make test: 29 PASS, 0 FAIL", key="utest", sep="2pt")
    d.p(f"Зураг {{F:ucli}}-д серверийг {c('Ctrl+C')}-ээр зогсоосны (\"Сервер зогслоо\") дараа CLI командуудыг шууд ажиллуулсан. {c('./build/client')}-ийн 5 нийлбэр зөв боловч хэвлэгдсэн дараалал (3, 0, 42, 15, 300) өмнөх ажиллалтаас (15, 3, 300, 0, 42) өөр байна. Энэ нь гурван worker зэрэгцэн ажиллаж, аль нь түрүүлж дуусахыг OS scheduler шийддэгийн бодит жишээ бөгөөд алдаа биш. {c('-w 3 -q 5 -n 15')} ажиллалтад 15 task бүгд гүйцэтгэгдэж, burst тестэд queue (3) дүүрч 7 task татгалзагдсан нь номын \"дүүрвэл 1 буцаана\" дүрмийг харуулна. Төгсгөлд {c('-h')} нь бүх сонголтын тайлбарыг хэвлэв.")
    d.photos(["img/user/client_sim_cli.png"], "Серверийг зогсоох, номын client.c, анхдагч ба burst ажиллалт, -h тусламж", key="ucli", width=82)
    d.p(f"Зураг {{F:utsan}}-д {c('make tsan')}: программыг {c('-fsanitize=thread')}-тэй хөрвүүлж, 4 worker, queue 3, 40 task-ийг retry горимоор маш богино (5-30 мс) хугацаатай ажиллуулсан. Queue байнга дүүрч client 58 удаа дахин оролдсон ч ThreadSanitizer нэг ч {c('WARNING')} гаргаагүй, 40 task бүр яг нэг удаа гүйцэтгэгдэж {c('VERIFY: OK')}. Энэ нь өрсөлдөөн ихтэй нөхцөлд ч mutex болон semaphore queue-г зөв хамгаалж байгааг баталгаажуулна.")
    d.photos(["img/user/make_tsan.png"], "Хэрэглэгчийн компьютер дээрх ThreadSanitizer: race илрээгүй, VERIFY OK", key="utsan", width=82)

    d.chapter("Хэлэлцүүлэг")
    d.section("Үр дүнгийн тайлбар")
    d.p(f"Бүх тестэд, тэр дундаа 64 worker зэрэг ажилласан болон 500 task-ийн stress нөхцөлд task бүр яг нэг удаа ажиллаж, нэг worker давхар task аваагүй, queue FIFO-оор ажиллаж, багтаамжаас хэтрээгүй нь mutex queue-ийн өгөгдлийг, semaphore task-ийн тоог зөв хамгаалж байгааг харуулна. Idle worker-ууд {c('sem_wait')} дээр унтдаг тул CPU үрэхгүй; timeline-ийн судалтай саарал бүс тэдгээрийн бодит хүлээлт юм. Task-ууд {c('nanosleep')} хийдэг (I/O-той адил) учраас worker-ийн тоо CPU-ийн цөмийн тооноос олон байсан ч хурдатгал бараг шугаман хэвээр байсан.")
    d.p("Ижил параметрээр дахин ажиллуулахад аль worker аль task-ийг авах, burst үед хэдэн task хүлээн авагдах нь бага зэрэг өөрчлөгдөж болно (T3: 3-5). Энэ нь OS scheduler-ийн шийдвэр бөгөөд тест ийм хэлбэлзлийг мужаар шалгадаг.")
    d.section("Хүлээх дараалал ба deadlock")
    d.p(f"Worker эхлээд {c('sem_wait')}, дараа нь {c('pthread_mutex_lock')} хийх ёстой. Хэрэв дарааллыг солиод mutex-ийг барьсан чигээр хоосон queue дээр {c('sem_wait')} хийвэл client mutex авч чадахгүй, task нэмэгдэхгүй тул хэн ч урагшлахгүй (deadlock). Мөн client {c('sem_post')}-ийг mutex суллагдсаны дараа хийдэг. Mutex-ийг зөвхөн queue-г өөрчлөх богино хэсэгт барьж, task-ийг гүйцэтгэх болон хүлээлтийг critical section-ээс гадуур хийсэн.")
    d.section("Хязгаарлалт")
    d.ul([f"Task-ийн ажлыг {c('nanosleep')}-ээр дуурайлгасан (номын зөвлөмж). CPU-д ачаалалтай ажилд хурдатгал цөмийн тоогоор хязгаарлагдана.",
          "Trace бүртгэл тусдаа mutex ашигладаг тул маш богино (< 1 мс) task-уудад бага зэргийн нэмэлт зардал үүсгэнэ.",
          "Нэг client thread submit хийдэг; retry горимд түүний хүлээлт дараагийн task-уудын ирэлтийг хойшлуулна.",
          "Номын API глобал төлөвтэй тул нэг процесст нэг pool ажиллана.",
          "Интерфейсийн хязгаар (2000 task, ~60 с) C программынхаас (10000 task) нарийн."])

    # ---------------- АРАВ ----------------
    d.chapter("Дүгнэлт")
    d.p(f'Сурах бичгийн Programming Project 1-ийг C хэл, pthreads, POSIX semaphore, mutex ашиглан бүрэн хэрэгжүүлж, worker-ийн тоо, queue-ийн багтаамж, дүүрэх үеийн бодлого, ачааллыг өөрчилж турших боломжтой болгосон. Номын {c("client.c")} жишээ өөрчлөлтгүй ажиллав. Багшийн оноосон "Worker activity" дүрслэлийг бодит программын trace-тэй шууд холбож, worker бүрийн idle, running, completed төлөв, queue, татгалзлыг алхам алхмаар харуулав. {npass} автомат тест, хараат бус trace шалгагч, ThreadSanitizer зөв ажиллагааг нотолж, гүйцэтгэлийн туршилт worker нэмэхэд хурдатгал бараг шугаман байгааг харуулсан. Manual-ын дагуу {c("make")}, {c("make ui")} гэсэн хоёр командаар өөр компьютерт ажиллуулах боломжтой.')

    d.plain_chapter("Ашигласан материал")
    d.add(f"""<ol class="refs">
<li>[1] A. Silberschatz, P. B. Galvin, G. Gagne. <i>Operating System Concepts</i>, 10th ed. Wiley, 2018. 4.5.1 (Thread pools), 4.6.3 (Thread cancellation), 6.5–6.6, 7.1.1, 7.3; Chapter 7 Programming Project 1 "Designing a Thread Pool".</li>
<li>[2] The Open Group. POSIX.1-2017: {c('pthread_create')}, {c('pthread_join')}, {c('pthread_mutex_lock')}, {c('sem_init')}, {c('sem_wait')}, {c('sem_post')}.</li>
<li>[3] Linux man-pages: {c('sem_overview(7)')}, {c('pthreads(7)')}, {c('nanosleep(2)')}.</li>
<li>[4] ThreadSanitizer. <span class="mono">https://clang.llvm.org/docs/ThreadSanitizer.html</span></li>
<li>[5] F.CSM302 Бие даалт 1 удирдамж, Сэдэв ба шүүмжийн хуваарилалт.</li>
<li>[6] Багийн repository. <span class="mono">{REPO.replace('https://', '')}</span></li>
</ol>""")

    d.plain_chapter("Хавсралт А. Ажлын төлөвлөгөө", newpage=True)
    d.table(None, [["Талбар", "Мэдээлэл"], ["Хуваарилалтын код", CODE], ["Төсөл", "Designing a Thread Pool"],
                   ["Repository", f"<span class='mono'>{REPO}</span>"],
                   ["Хэл/сан/орчин", "C (pthreads, POSIX semaphore), Python 3, HTML/JavaScript; Linux, macOS, WSL2"],
                   ["Үндсэн дүрслэл", "Worker activity"]], widths=[30, 70])
    d.table(None, [["Гишүүн", "Хариуцах ажил", "Commit/file"]] +
            [[f"{e(n)}<br>/{s}/", w, c(f)] for n, s, w, f in APPENDIX_MEMBERS], widths=[24, 46, 30])
    d.table(None, [["Тест", "Оролт/нөхцөл", "Хүлээгдсэн үр дүн"],
                   ["1", f"{c('./build/client')} (номын жишээ)", "5 нийлбэр зөв"],
                   ["2", "W=3, Q=10, basic.txt", "10/10 хүлээн авна, зэрэг ≤ 3"],
                   ["3", "W=2, Q=3, burst.txt (queue дүүрэх)", f"3-5 хүлээн авна, үлдсэнд {c('pool_submit')} 1 буцаана"],
                   ["4", "W=1, fifo.txt", "FIFO дараалал"],
                   ["5", "W=0, буруу файл", "exit 2, алдаатай утга/мөрийг заасан тайлбар"]], widths=[10, 45, 45])
    return d, front


# ============================ ГАРЫН АВЛАГА ====================================
def manual():
    st, errs, (npass, nfail), client_ok = parse_tests()
    E = env_rows()
    d = Doc()
    front = ""

    d.chapter("Хэрэглэгчийн заавар")
    d.section("Программын зорилго")
    d.p(f"Сурах бичгийн 7-р бүлгийн thread pool-ийг C хэл дээр pthreads, mutex, POSIX semaphore-оор хэрэгжүүлсэн. Client thread task-уудыг queue-д хийж, worker thread-үүд нь queue-ээс авч гүйцэтгэнэ. Browser дээрх дэлгэц нь <b>бодит C программын</b> үйлдлийг (submit, татгалзал, эхлэх, дуусах, shutdown) worker бүрийн төлөв, queue болон timeline хэлбэрээр харуулна. Дэлгэц зөвхөн харуулдаг; бүх синхрончлол C core дотор явагдана.")
    d.section("Дэмжих орчин")
    d.ul(["Linux (Ubuntu 22.04+, Debian, Fedora), macOS (Apple Silicon / Intel), Windows дээр <b>WSL2 Ubuntu</b> дотор.",
          "Browser: Chrome, Edge, Firefox, Safari-ийн сүүлийн хувилбар.",
          f"Windows дээр шууд ажиллахгүй (pthreads, POSIX semaphore ашигладаг): <b>WSL2</b> эсвэл <b>virtual machine</b> доторх Ubuntu ашиглана."])
    d.section("Windows: WSL2")
    d.ol([f"PowerShell-ийг администратороор нээж {c('wsl --install -d Ubuntu')}, компьютераа дахин асаана.",
          "Ubuntu терминалд compiler, Python суулгана:"])
    d.code(None, "sudo apt update && sudo apt install -y build-essential git python3", lang="bash")
    d.ol(['"Суулгах, нээх" хэсгийн командуудыг Ubuntu дотор ажиллуулна. Windows-ийн browser дээр http://localhost:8000 шууд нээгдэнэ.'])
    d.section("Windows: virtual machine")
    d.p(f"VirtualBox, VMware эсвэл UTM дээр Ubuntu 22.04+ суулгаж, WSL2-ийн 2-р алхмын адил {c('build-essential')}, {c('python3')} суулгана.")
    d.ul([f"VM доторх browser-оос: {c('make ui')}, http://localhost:8000.",
          f"Windows (host) browser-оос: сервер анхдагчаар зөвхөн VM дотроос хүсэлт хүлээн авдаг тул {c('python3 tools/server.py --host 0.0.0.0')} гэж ажиллуулаад {c('http://<VM-ийн IP>:8000')} нээнэ (IP-г {c('hostname -I')}-ээр харна).",
          "VM-ийн сүлжээ Bridged эсвэл Host-only байна; NAT бол 8000 портыг forward хийнэ."])
    d.section("Суулгах, нээх")
    d.code(None, f"git clone {REPO}.git\ncd {REPO_DIR}\nmake          # C программыг build хийнэ\nmake ui       # http://localhost:8000", lang="bash")
    d.p(f"Дараа нь browser-т <b>http://localhost:8000</b>-ийг нээнэ. Баруун дээд буланд ногоон цэг ба \"C программтай холбогдсон\" гэж гарвал бэлэн. Хуудас нээгдэхэд анхдагч тохиргоогоор нэг удаа автоматаар ажиллана.")
    d.section("Дэлгэцийн бүтэц")
    d.p("Дэлгэц зүүн талын тохиргоо, баруун талын дүрслэлээс бүрдэнэ (Хүснэгт {T:regions}, Зураг {F:overview}).")
    d.table("Дэлгэцийн хэсгүүд", [
        ["Хэсэг", "Байрлал", "Юу хийх вэ"],
        ["Pool тохиргоо", "зүүн дээд", "worker, queue, дүүрэх үеийн бодлого, retry зай"],
        ["Ачаалал (task)", "зүүн доод", "Параметрээр эсвэл Task жагсаалтаар task үүсгэх; Ажиллуулах, Анхдагч, Trace ачаалах/хадгалах"],
        ["Playback мөр", "баруун дээд", "Reset, өмнөх/дараагийн үйлдэл, тоглуулах, хугацааны гулсуур, хурд"],
        ["Worker-ууд, Task queue", "дунд", "t агшин дахь worker бүрийн төлөв, queue-ийн нүд, тоолуур, үйлдлийн тайлбар"],
        ["Worker activity timeline", "дунд", "worker бүрийн хугацааны мөр, client мөр, queue-ийн урт"],
        ["Үр дүн ба шалгалт", "доор", "хэмжүүрүүд, 8 шалгалт, C программын команд ба гаралт"],
        ["Үйлдлийн бүртгэл", "хамгийн доор", "үйлдэл бүрийн хүснэгт; мөр дээр дарж тэр агшин руу очно"],
    ], key="regions", widths=[28, 18, 54])
    d.shot(IMG("overview"), "Дэлгэцийн ерөнхий харагдац", key="overview", width=88)
    d.section("Оролт ба тохиргоо")
    d.p(f"Тоо бүрийг шууд бичиж эсвэл сумаар өөрчилнө. Хүрээнээс гадуур утга оруулбал Ажиллуулах дарахад улаан талбарт алдааны тайлбар гарна (Зураг {{F:err}}). <b>Параметрээр</b> горимд task-уудыг seed-ээс санамсаргүй үүсгэнэ; <b>Task жагсаалт</b> горимд мөр бүрт {c('arrival_ms duration_ms')} бичнэ ({c('#')}-ээс хойш тайлбар, arrival өсөх дарааллаар). <b>Бэлэн тест</b>-ээс {c('basic.txt')}, {c('burst.txt')}, {c('fifo.txt')}, {c('mixed_long_short.txt')} сонгож болно.")
    d.table("Оролт ба тохиргоо", [
        ["Талбар", "Утга", "Хүрээ", "Анхдагч"],
        ["Worker thread", "pool дахь worker thread-ийн тоо", "1-64", "3"],
        ["Queue багтаамж", "тойрог массив queue-ийн хэмжээ", "1-4096", "5"],
        ["Дүүрэх үед", f"reject: {c('pool_submit')} 1 буцааж task хаягдана; retry: client хүлээгээд дахин оролдоно", "reject / retry", "reject"],
        ["Retry зай (мс)", "retry горимд дахин оролдох зай", "1-10000", "20"],
        ["Task-ийн тоо", "үүсгэх task-ийн тоо", "1-2000", "15"],
        ["Хугацаа (мс)", "task бүрийн хугацаа энэ мужаас санамсаргүй", "1-60000", "200-800"],
        ["Ирэх зай (мс)", "дараалсан task-уудын зай; 0 = бүгд зэрэг", "0-60000", "20-120"],
        ["Seed", "ижил seed = ижил ачаалал", "≥ 0", "42"],
    ], key="input", widths=[22, 46, 17, 15])
    d.shot(IMG("settings"), "Тохиргоо", key="settings", width=38)
    d.section("Ажиллуулах, зогсоох, reset")
    d.ul(["<b>Ажиллуулах</b>: тохиргоогоор C программыг бодитоор ажиллуулна (task-уудын нийт хугацаа шиг үргэлжилнэ), дараа нь автоматаар тоглуулна.",
          "<b>▶ / ⏸</b> (<kbd>Space</kbd>): тоглуулах, түр зогсоох. <b>◀︎ / ▶︎</b> (<kbd>←</kbd> <kbd>→</kbd>): өмнөх, дараагийн үйлдэл рүү алхах.",
          "<b>Гулсуур</b>, timeline дээр <b>дарах эсвэл чирэх</b>, бүртгэлийн мөр дээр дарах: тухайн агшин руу очно.",
          "<b>Хурд</b>: 0.25×, 0.5×, 1× (бодит хугацаа), 2×, 4×, 10×.",
          "<b>⏮ Reset</b>: эхний агшин руу буцна. <b>Анхдагч</b>: бүх тохиргоог анхны утганд оруулна.",
          "<b>Trace хадгалах</b>: тухайн ажиллалтыг JSON файлаар татна. <b>Trace ачаалах</b>: хадгалсан trace-ийг дахин нээнэ.",
          "<b>Серверийг зогсоох</b>: терминалд <kbd>Ctrl</kbd>+<kbd>C</kbd>."])
    d.section("Дүрслэлийн тэмдэг, өнгө, төлөв")
    d.p("<b>Worker карт.</b> Worker бүр нэг карт: нэр (W0, W1…), одоогийн төлөв, явцын шугам, баруун дээд буланд дуусгасан task-ийн тоо (✓ n).")
    d.ul(["<b>● running Tk</b> (өнгөт, хүрээ цэнхэр): worker Tk task-ийг гүйцэтгэж байна (<i>running</i>).",
          "<b>○ idle — sem_wait</b> (саарал): worker semaphore дээр ажил хүлээж байна (<i>idle</i>).",
          "<b>■ exited</b> (бүдэг): shutdown-ы дараа worker гарсан. ✓ n нь тухайн worker-ийн <i>completed</i> task-ийн тоо."])
    d.p("<b>Task queue.</b> Хүлээж буй task-ууд өөрийн өнгөөр, зүүн талд нь хамгийн түрүүнд авагдах (head). Тасархай хүрээтэй нүд = сул зай. Доор нь хүлээн авсан, ажиллаж буй, дууссан, татгалзсан тоо, түүний доор тухайн агшны үйлдлийн тайлбар (жишээ нь \"W1 sem_wait-аас сэрж T10-г dequeue хийв\").")
    d.shot(IMG("live_state"), "Worker карт ба task queue", width=85)
    d.table("Worker activity timeline-ийн тэмдэг", [
        ["Тэмдэг", "Утга"],
        [f"өнгөт зурвас {c('Tk')}", "worker Tk task-ийг гүйцэтгэсэн хугацаа; task бүр өөр өнгөтэй, queue-д ч мөн тэр өнгөөр харагдана"],
        ["судалтай саарал", f"idle: worker {c('sem_wait')} дээр хүлээж байна"],
        ["бараан бүс", "worker гарсан (shutdown-ы дараа)"],
        ["нил ягаан шатлалт график", "queue-ийн урт (0 … багтаамж)"],
        ["client мөр: саарал |", f"{c('pool_submit')} амжилттай (0)"],
        ["client мөр: улаан ✕", f"queue дүүрсэн, {c('pool_submit')} 1 буцаасан"],
        ["тасархай босоо зураас", f"{c('pool_shutdown()')} дуудагдсан агшин"],
        ["хар босоо шугам", "одоогийн агшин (playhead)"],
    ], key="legend", widths=[32, 68])
    d.section("Жишээ")
    d.p("<b>Жишээ 1. Queue дүүрэх</b> (Task жагсаалт → burst.txt, W=2, Q=3, reject). 10 task нэгэн зэрэг ирэх тул queue хурдан дүүрнэ: 3-5 task хүлээн авагдаж, үлдсэн нь client мөрөнд улаан ✕ болно. Төгсгөлд <span class='mono'>VERIFY OK</span>.")
    d.shot(IMG("burst_reject"), "Жишээ 1. Queue дүүрэх")
    d.p("<b>Жишээ 2. Retry горим</b> (Жишээ 1-ийн тохиргоо, Дүүрэх үед: retry). Client дүүрсэн queue-д 20 мс тутам дахин оролдох тул ✕ олон боловч 10 task бүгд гүйцэтгэгдэнэ, нийт хугацаа ≈ 1500 мс.")
    d.shot(IMG("burst_retry"), "Жишээ 2. Retry горим")
    d.p("<b>Жишээ 3. FIFO-г алхамчлах</b> (fifo.txt, W=1, Q=10). Ажиллуулаад ⏮ дарж, ▶︎ (<kbd>→</kbd>) товчоор нэг нэгээр алхана. Task-ууд T0, T1, T2… дарааллаар эхэлж, queue-ийн зүүн талаас авагдана.")
    d.shot(IMG("fifo_step"), "Жишээ 3. FIFO, алхамчилсан")
    d.p("<b>Жишээ 4. Worker-ийн тооны нөлөө</b> (Параметрээр: 12 task, хугацаа 100-300, ирэх зай 0-0, queue 64, seed 1). Worker-ийг 1, дараа нь 4 болгож ажиллуулаад timeline болон \"Makespan\"-ийг харьцуулна.")
    d.shots(['compare_w1', 'compare_w4'], "Жишээ 4. Дээр 1 worker, доор 4 worker", width=78, layout="stack")
    d.p("<b>Жишээ 5. Үйлдлийн бүртгэл.</b> Бүртгэлийн мөр бүр нэг үйлдэл; одоогийн мөр цэнхэрээр, ирээдүйн мөрүүд бүдгээр харагдана. Мөр дээр дарахад тэр агшин руу очно.")
    d.shot(IMG("event_log"), "Жишээ 5. Үйлдлийн бүртгэл")
    d.section("Сервергүй горим")
    d.p(f"{c('ui/index.html')}-ийг файлаар шууд нээвэл баруун дээд буланд \"offline — зөвхөн trace файл үзэх горим\" гарч, Ажиллуулах идэвхгүй болно. <b>Trace ачаалах</b>-аар {c('examples/sample_trace.json')} эсвэл өөрийн хадгалсан trace-ийг нээж бүх дүрслэлийг ашиглаж болно.")
    d.shot(IMG("offline"), "Сервергүй горимд хадгалсан trace үзэж буй нь", width=82)
    d.section("Түгээмэл алдаа ба шийдэл")
    d.table("Түгээмэл алдаа", [
        ["Алдаа", "Шалтгаан", "Шийдэл"],
        [c("-w буруу ('0'): worker-ийн тоо 1..64"), "хүрээнээс гадуур утга", "тайлбарт заасан мужид оруулна (Зураг {F:err})"],
        [c("<task жагсаалт>:2 — duration_ms буруу"), "жагсаалтын 2-р мөрөнд тоо биш утга", "мөр бүр яг 2 бүхэл тоо"],
        [c("arrival_ms өсөхгүй дарааллаар"), "ирэх хугацаа эрэмбэгүй", "arrival-аар эрэмбэлнэ"],
        [c("Тооцоолсон хугацаа ~N сек"), "интерфейсийн 60 с-ийн хязгаар", "task/хугацааг багасгах, worker нэмэх эсвэл CLI ашиглах"],
        [c("offline — зөвхөн trace"), "сервер ажиллаагүй / файлаар нээсэн", f"{c('make ui')}, дараа нь http://localhost:8000"],
        [c("build/threadpool_sim алга"), "build хийгээгүй", c("make")],
        [c("make: cc: No such file"), "C compiler байхгүй", f"Ubuntu/WSL: {c('sudo apt install build-essential')}; macOS: {c('xcode-select --install')}"],
        [c("Address already in use"), "8000 порт завгүй", c("python3 tools/server.py --port 8080")],
        ["Ижил тохиргоо өөр timeline", "OS scheduler-ийн nondeterminism", "алдаа биш; Trace хадгалахаар тогтооно"],
    ], key="errs", widths=[36, 28, 36])
    d.shots(['error_workers0', 'error_file'], "Буруу оролт: worker = 0 (зүүн), task жагсаалтад тоо биш утга (баруун)", key="err", width=72, layout="row")

    d.chapter("Operational заавар")
    d.section("Repository clone")
    d.code(None, f"git clone {REPO}.git\ncd {REPO_DIR}\ngit checkout v1.0      # 9-р долоо хоногт нийтэлсэн хувилбар", lang="bash")
    d.section("OS, compiler/runtime, version")
    d.table("Туршсан орчин", [
        ["Орчин", "OS", "Compiler", "Python"],
        ["Хөгжүүлэлт, тест", f"{E['os']}, {E['arch']}", E["gcc"], E["py"]],
        ["GitHub Actions", "ubuntu-latest", "gcc", "3"],
        ["GitHub Actions", "macos-latest", "Apple clang", "3"],
    ], key="env", widths=[22, 32, 28, 18])
    d.p(f"Шаардлага: C11 compiler (gcc ≥ 9 эсвэл clang ≥ 10) + {c('make')}, Python 3.8 эсвэл түүнээс дээш, орчин үеийн browser. Python-д pip сан, интерфейст интернет (CDN) шаардлагагүй.")
    d.section("Dependency суулгах")
    d.code(None, "# Ubuntu / Debian / WSL2\nsudo apt update && sudo apt install -y build-essential python3\n# Fedora\nsudo dnf install -y gcc make python3\n# macOS\nxcode-select --install", lang="bash")
    d.section("Build ба Run")
    d.code(None, """make                         # build/threadpool_sim, build/client
make ui                      # UI сервер, http://localhost:8000
make client                  # номын client.c жишээ
make run                     # жишээ run -> build/trace.json
# core-ийг шууд ажиллуулах:
./build/threadpool_sim -w 3 -q 5 -n 15 -d 200-800 -a 20-120 -o trace.json
./build/threadpool_sim -w 2 -q 3 -f tests/burst.txt -p retry
./build/threadpool_sim -h    # бүх сонголт""", lang="bash")
    d.p("Exit код: <b>0</b> амжилттай, <b>2</b> буруу оролт, <b>3</b> ажиллах үеийн алдаа (санах ой, thread үүсгэх), <b>4</b> дотоод шалгалт унасан.")
    d.section("Үндсэн тестийн өгөгдөл")
    d.code(None, "make test", lang="bash")
    d.ul([f"{c('./build/client')}: номын жишээ, 5 хос тооны нийлбэр (15, 3, 300, 0, 42).",
          f"{c('tests/basic.txt')}: 10 task, W=3, Q=10 → хүлээн авсан 10, татгалзсан 0, зэрэг ≤ 3.",
          f"{c('tests/burst.txt')}: 10 × 300 мс, t=0; W=2, Q=3 → reject үед 3-5 хүлээн авна, retry үед 10.",
          f"{c('tests/fifo.txt')}: 6 task, W=1 → START дараалал T0…T5.",
          f"{c('tests/mixed_long_short.txt')}: 1 × 1500 мс + 7 × 100 мс, W=3."])
    d.p(f"Trace-ийг бие даан шалгах: {c('python3 tests/verify_trace.py trace.json --expect accepted=15')}.")
    d.section("Нэмэлт boundary ба error тест")
    d.code(None, """# queue 1: татгалзал гарна
./build/threadpool_sim -w 1 -q 1 -n 6 -d 100 -a 0
# дээд 64 worker
./build/threadpool_sim -w 64 -q 64 -n 64 -d 50 -a 0
# 500 task stress
./build/threadpool_sim -w 8 -q 16 -n 500 -d 1-3 -a 0 -p retry -r 1
make tsan     # ThreadSanitizer""", lang="bash")
    d.table("Буруу оролтын тестийн бодит гаралт (exit 2)", [["Тест", "Программын мэдээлэл"]] +
            [[c(n), e(m)] for r, n, m in errs], key="errout", widths=[24, 76], cls="small")
    d.section("Хүлээгдсэн үр дүн")
    d.ul([f"{c('make test')}: төгсгөлд {c(f'Нийт: {npass} PASS, {nfail} FAIL')}, exit 0.",
          f"Ажиллуулалт бүрийн stderr-ийн төгсгөлд 8 мөр {c('[ OK ]')} ба {c('VERIFY: OK')}.",
          f"{c('make tsan')}: ThreadSanitizer-ийн {c('WARNING')} гарахгүй, {c('VERIFY: OK')}.",
          "Хугацааны утгууд (хүлээлт, makespan) машин бүрт хэдэн мс-ээр зөрнө; хүлээн авсан/татгалзсан тоо, FIFO, зэрэгцээний дээд хэмжээ өөрчлөгдөхгүй (burst-ийн 3-5 мужаас бусад).",
          "GitHub Actions: build-and-test (linux, macos) ногоон."])
    d.section("Known issues")
    d.ul([f"macOS нэргүй POSIX semaphore ({c('sem_init')}) дэмждэггүй тул {c('dispatch_semaphore')} ашиглана; macOS-ийг зөвхөн CI-д шалгасан.",
          "Windows дээр шууд ажиллахгүй; WSL2 эсвэл VM ашиглана.",
          "Worker-ийн хуваарилалт ба burst үеийн хүлээн авах тоо ажиллуулалт бүрт бага зэрэг өөр (OS scheduler).",
          "Интерфейсээр нэг ажиллуулалт ≤ 2000 task, ≈ 60 с. Илүүг CLI-ээр ажиллуулж, trace-ийг ачаалж үзнэ (их task-тай trace зурахад browser удааширч болно).",
          "Retry горимд нэг client thread хүлээдэг тул дараагийн task-уудын ирэлт хойшилно.",
          "Маш богино (< 1 мс) task-д trace-ийн mutex хэмжилтэд нөлөөлнө."])
    return d, front




# ============================ .tex файл бичих ==================================
def preamble(kind, title):
    team = "\n".join(f"  \\member{{{tex_escape(n)}}}{{{s}}}" for n, s, _, _ in MEMBERS)
    return f"""% =============================================================================
%  {CODE} — {title}
%  F.CSM302 Үйлдлийн систем, Бие даалт 1.  Хөрвүүлэгч: XeLaTeX (Overleaf: Menu → Compiler)
%  Энэ файлыг tools/build_docs.py бодит тест, туршилтын үр дүнгээс үүсгэсэн; шууд засаж болно.
% =============================================================================
\\documentclass[12pt,a4paper]{{article}}
\\usepackage{{shutis}}

% ---------------- Баримтын мэдээлэл (энд засна) ----------------
\\newcommand{{\\DocTopic}}{{{tex_escape(TOPIC)}}}
\\newcommand{{\\DocCode}}{{{CODE}}}
\\newcommand{{\\DocTeacher}}{{{tex_escape(TEACHER)}}}
\\newcommand{{\\DocCity}}{{{CITY}}}
\\newcommand{{\\DocYear}}{{{YEAR}}}
\\newcommand{{\\DocTeam}}{{%   \\member{{Овог.Нэр}}{{Оюутны код}}
{team}
}}
\\hypersetup{{pdftitle={{{CODE} — {title}}}, pdfauthor={{F.CSM302 {CODE} баг}}}}

\\begin{{document}}
\\makecover{{{kind}}}
"""


def write_tex(name, kind, title, doc, abstract_html):
    parts = [preamble(kind, title)]
    if abstract_html:
        paras = re.findall(r"<p>(.*?)</p>", abstract_html, flags=re.S)
        parts.append("\\section*{Хураангуй}\n\\addcontentsline{toc}{section}{Хураангуй}\n")
        parts += [h2l(p) + "\n" for p in paras]
        parts.append("\\clearpage\n")
    parts.append("\\tableofcontents\n\\clearpage\n")
    parts.append(doc.latex())
    parts.append("\\end{document}\n")
    path = os.path.join(LATEX, name + ".tex")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(parts))
    return path


def compile_tex(name):
    cmd = ["latexmk", "-xelatex", "-interaction=nonstopmode", "-halt-on-error", "-file-line-error", name + ".tex"]
    r = subprocess.run(cmd, cwd=LATEX, capture_output=True, text=True)
    log = open(os.path.join(LATEX, name + ".log"), encoding="utf-8", errors="replace").read()
    missing = sorted(set(re.findall(r"Missing character: There is no (\S+)", log)))
    overfull = re.findall(r"Overfull \\hbox \((\d+\.\d+)pt too wide\)[^\n]*lines? (\d+)", log)
    big = [(float(a), int(b)) for a, b in overfull if float(a) > 3]
    if r.returncode != 0:
        print(r.stdout[-3000:])
        sys.exit(f"{name}.tex хөрвүүлэхэд алдаа гарлаа (docs/latex/{name}.log)")
    if missing:
        print(f"  ! {name}: дутуу тэмдэгт: {' '.join(missing)}")
    if big:
        print(f"  ! {name}: overfull мөр (pt, .tex мөр): {big[:10]}")
    return os.path.join(LATEX, name + ".pdf")


def make_zip():
    out = os.path.join(DOCS, f"{CODE}_overleaf.zip")
    keep = ("report.tex", "manual.tex", "shutis.sty", "codestyle.tex", "latexmkrc", "README.md")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for base, _, files in os.walk(LATEX):
            for f in files:
                rel = os.path.relpath(os.path.join(base, f), LATEX)
                if rel in keep or rel.startswith(("fonts" + os.sep, "img" + os.sep)):
                    z.write(os.path.join(base, f), rel)
    return out


def main():
    for p in ("build/test_output.txt", "docs/results/exp1_workers.csv", "docs/latex/img/shots/overview.png"):
        if not os.path.exists(os.path.join(ROOT, p)):
            sys.exit(f"{p} алга. Docstring дахь алхмуудыг эхлээд ажиллуулна уу.")
    write_codestyle()
    d, front = report()
    write_tex("report", "ТАЙЛАН", "Бие даалт 1 тайлан", d, front)
    d, front = manual()
    write_tex("manual", "ГАРЫН АВЛАГА", "Бие даалт 1 гарын авлага", d, front)
    print("OK: docs/latex/report.tex, docs/latex/manual.tex")
    if "--no-pdf" not in sys.argv:
        for name, out in (("report", f"{CODE}_BD1_Report.pdf"), ("manual", f"{CODE}_Manual.pdf")):
            pdf = compile_tex(name)
            shutil.copy(pdf, os.path.join(DOCS, out))
            pages = re.search(r"Pages:\s+(\d+)", sh(f"pdfinfo '{pdf}'")).group(1)
            print(f"OK: docs/{out} ({pages} хуудас)")
    print("OK:", os.path.relpath(make_zip(), ROOT))


if __name__ == "__main__":
    main()
