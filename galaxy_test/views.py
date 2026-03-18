import json
import os
import tempfile
import re
import time
import threading
import urllib.parse
import pandas as pd
from django.conf import settings
from django.http import HttpResponse, JsonResponse, StreamingHttpResponse
from bioblend.galaxy import GalaxyInstance
from django.shortcuts import render
from decouple import config
import requests
from django.shortcuts import redirect
from django.contrib.auth.decorators import login_required

GALAXY_URL = settings.GALAXY_URL
GALAXY_API_KEY = settings.GALAXY_API_KEY

_pipeline_state = {}

def get_api_key(request):
    try:
        return request.user.galaxyprofile.galaxy_api_key
    except Exception:
        return settings.GALAXY_API_KEY

@login_required(login_url='/user/login/')
def index(request):
    return render(request, 'index.html', {})

def obtener_historias(request):
    api_key = get_api_key(request)
    gi = GalaxyInstance(settings.GALAXY_URL, key=api_key)
    return gi.histories.get_histories(keys=['id', 'name', 'count', 'update_time'])

def listar_historias(request):
    return JsonResponse(obtener_historias(request), safe=False)

def crear_historia(request):
    if request.method == "POST":
        nombre_historia = request.POST.get('nombre_historia')
        api_key = get_api_key(request)
        gi = GalaxyInstance(settings.GALAXY_URL, api_key)
        gi.histories.create_history(nombre_historia)
        return render(request, 'crear_historia.html', {
            "mensaje": f"Historia '{nombre_historia}' creada con éxito ✦"
        })
    return render(request, 'crear_historia.html')

def subir_archivo(request):
    if request.method == "POST":
        archivo = request.FILES["archivo"]
        history_id = request.POST["history_id"]
        temp_dir = tempfile.gettempdir()
        ruta_temp = os.path.join(temp_dir, archivo.name)
        with open(ruta_temp, "wb+") as destino:
            for chunk in archivo.chunks():
                destino.write(chunk)
        api_key = get_api_key(request)
        gi = GalaxyInstance(settings.GALAXY_URL, key=api_key)
        gi.tools.upload_file(path=ruta_temp, history_id=history_id, file_name=archivo.name)
        os.remove(ruta_temp)
        return redirect('subir_archivo')
    historias = obtener_historias(request)
    return render(request, "subir_archivo.html", {'historias': historias})

def esperar_finalizacion(gi, job_id, session_key=None, intervalo=10):
    while True:
        if session_key:
            state = _pipeline_state.get(session_key, {})
            if state.get("cancelado"):
                raise Exception("Pipeline cancelado por el usuario")
        job = gi.jobs.show_job(job_id)
        estado = job.get("state")
        if estado in ["ok", "error"]:
            break
        time.sleep(intervalo)

def obtener_datasets_con_estado(gi, outputs):
    resultado = []
    for d in outputs.values():
        try:
            info = gi.datasets.show_dataset(d["id"])
            resultado.append({"id": d["id"], "state": info.get("state", "desconocido")})
        except Exception:
            resultado.append({"id": d["id"], "state": "desconocido"})
    return resultado

def ejecutar_fastqc(history_id, datsets, api_key, session_key=None):
    gi = GalaxyInstance(url=GALAXY_URL, key=api_key)
    results = {}
    for dataset in datsets:
        tool_inputs = {"input_file": {"src": "hda", "id": dataset}}
        job = gi.tools.run_tool(
            history_id=history_id,
            tool_id="toolshed.g2.bx.psu.edu/repos/devteam/fastqc/fastqc/0.72",
            tool_inputs=tool_inputs,
        )
        job_id = job["jobs"][0]["id"]
        if session_key:
            _pipeline_state[session_key]["job_activo"] = job_id
        esperar_finalizacion(gi, job_id, session_key)
        info = gi.jobs.show_job(job_id)
        outputs = info.get("outputs", {})
        output_datasets = obtener_datasets_con_estado(gi, outputs)
        results[dataset] = {"job_id": job_id, "output_datasets": output_datasets, "outputs_raw": outputs}
    return results

def ejecutar_trimmomatic(history_id, unaligned_R1, unaligned_R2, api_key, session_key=None):
    gi = GalaxyInstance(url=GALAXY_URL, key=api_key)
    tool_inputs = {
        "readtype|single_or_paired": "pair_of_files",
        "readtype|fastq_r1_in": {"src": "hda", "id": unaligned_R1},
        "readtype|fastq_r2_in": {"src": "hda", "id": unaligned_R2},
        "illuminaclip|do_illuminaclip": "no",
    }
    job = gi.tools.run_tool(
        history_id=history_id,
        tool_id="toolshed.g2.bx.psu.edu/repos/pjbriggs/trimmomatic/trimmomatic/0.39+galaxy2",
        tool_inputs=tool_inputs,
    )
    job_id = job["jobs"][0]["id"]
    if session_key:
        _pipeline_state[session_key]["job_activo"] = job_id
    esperar_finalizacion(gi, job_id, session_key)
    info = gi.jobs.show_job(job_id)
    outputs = info.get("outputs", {})
    output_datasets = obtener_datasets_con_estado(gi, outputs)
    paired_R1 = outputs.get("fastq_out_r1_paired", {}).get("id")
    paired_R2 = outputs.get("fastq_out_r2_paired", {}).get("id")
    return job_id, output_datasets, paired_R1, paired_R2

def ejecutar_bowtie(history_id, datasetID_R1, datasetID_R2, genomaId, api_key, session_key=None):
    gi = GalaxyInstance(url=GALAXY_URL, key=api_key)
    tool_inputs = {
        "library|type": "paired",
        "library|input_1": {"src": "hda", "id": datasetID_R1},
        "library|input_2": {"src": "hda", "id": datasetID_R2},
        "library|unaligned_file": "true",
        "library|aligned_file": "true",
        "library|paired_options|paired_options_selector": "no",
        "reference_genome|source": "history",
        "reference_genome|own_file": {"src": "hda", "id": genomaId},
    }
    job = gi.tools.run_tool(
        history_id=history_id,
        tool_id="toolshed.g2.bx.psu.edu/repos/devteam/bowtie2/bowtie2/2.5.3+galaxy0",
        tool_inputs=tool_inputs,
    )
    job_id = job["jobs"][0]["id"]
    if session_key:
        _pipeline_state[session_key]["job_activo"] = job_id
    esperar_finalizacion(gi, job_id, session_key)
    info = gi.jobs.show_job(job_id)
    outputs = info.get("outputs", {})
    output_datasets = obtener_datasets_con_estado(gi, outputs)
    unaligned_R1 = outputs.get("output_unaligned_reads_r", {}).get("id")
    unaligned_R2 = outputs.get("output_unaligned_reads_l", {}).get("id")
    return job_id, output_datasets, unaligned_R1, unaligned_R2

def ejecutar_shovill(history_id, paired_R1, paired_R2, type_assembler, api_key, session_key=None):
    gi = GalaxyInstance(url=GALAXY_URL, key=api_key)
    tool_inputs = {
        "library|lib_type": "paired",
        "library|R1": {"src": "hda", "id": paired_R1},
        "library|R2": {"src": "hda", "id": paired_R2},
        "assembler": type_assembler
    }
    job = gi.tools.run_tool(
        history_id=history_id,
        tool_id="toolshed.g2.bx.psu.edu/repos/iuc/shovill/shovill/1.1.0+galaxy2",
        tool_inputs=tool_inputs,
    )
    job_id = job["jobs"][0]["id"]
    if session_key:
        _pipeline_state[session_key]["job_activo"] = job_id
    esperar_finalizacion(gi, job_id, session_key)
    info = gi.jobs.show_job(job_id)
    outputs = info.get("outputs", {})
    output_datasets = obtener_datasets_con_estado(gi, outputs)
    shovill = outputs.get("contigs", {}).get("id")
    return job_id, output_datasets, shovill

def ejecutar_quast(history_id, contigs, api_key, session_key=None):
    gi = GalaxyInstance(url=GALAXY_URL, key=api_key)
    results = {}
    datasets_calidad = {}
    winner = None
    quast_html_ids = {}

    for contigId in contigs:
        tool_inputs = {
            "mode|mode": "individual",
            "mode|in|custom": "false",
            "mode|in|inputs": {"src": "hda", "id": contigId},
            "output_files": ["html", "tabular"]
        }
        job = gi.tools.run_tool(
            history_id=history_id,
            tool_id="toolshed.g2.bx.psu.edu/repos/iuc/quast/quast/5.3.0+galaxy1",
            tool_inputs=tool_inputs,
        )
        job_id = job["jobs"][0]["id"]
        if session_key:
            _pipeline_state[session_key]["job_activo"] = job_id
        esperar_finalizacion(gi, job_id, session_key)
        info = gi.jobs.show_job(job_id)
        outputs = info.get("outputs", {})
        output_datasets = obtener_datasets_con_estado(gi, outputs)
        id_tsv = outputs['report_tabular']['id']
        ruta = '/tmp/report.tsv'
        gi.datasets.download_dataset(id_tsv, file_path=ruta, use_default_filename=False)
        data_tsv = pd.read_csv(ruta, sep="\t", index_col=0)
        n50 = data_tsv.loc["N50"].values[0]
        l50 = data_tsv.loc["L50"].values[0]
        datasets_calidad[contigId] = {'N50': n50, 'L50': l50}
        os.remove(ruta)
        results[contigId] = {"job_id": job_id, "output_datasets": output_datasets}
        # Guardar ID del HTML de QUAST
        if 'report_html' in outputs:
            quast_html_ids[contigId] = outputs['report_html']['id']

        if len(datasets_calidad) == 2:
            c0, c1 = contigs[0], contigs[1]
            if datasets_calidad[c0]['N50'] > datasets_calidad[c1]['N50'] and datasets_calidad[c0]['L50'] < datasets_calidad[c1]['L50']:
                winner = c0
            elif datasets_calidad[c0]['N50'] > datasets_calidad[c1]['N50']:
                winner = c0
            else:
                winner = c1

    return results, winner, datasets_calidad, quast_html_ids

def ejecutar_augustus(history_id, shovill, api_key, session_key=None):
    gi = GalaxyInstance(url=GALAXY_URL, key=api_key)
    tool_inputs = {"input_genome": {"src": "hda", "id": shovill}}
    job = gi.tools.run_tool(
        history_id=history_id,
        tool_id="toolshed.g2.bx.psu.edu/repos/bgruening/augustus/augustus/3.5.0+galaxy0",
        tool_inputs=tool_inputs,
    )
    job_id = job["jobs"][0]["id"]
    if session_key:
        _pipeline_state[session_key]["job_activo"] = job_id
    esperar_finalizacion(gi, job_id, session_key)
    info = gi.datasets.show_dataset(job_id)
    outputs = info.get("outputs", {})
    return job_id, outputs

def _descargar_reporte_fastqc(gi, job_result, nombre_archivo):
    """Descarga el HTML de FastQC y lo guarda en media/reportes/fastqc/"""
    try:
        outputs_raw = job_result.get("outputs_raw", {})
        html_id = outputs_raw.get("html_file", {}).get("id")
        if not html_id:
            return None
        carpeta = os.path.join(settings.MEDIA_ROOT, 'reportes', 'fastqc')
        os.makedirs(carpeta, exist_ok=True)
        ruta = os.path.join(carpeta, nombre_archivo)
        gi.datasets.download_dataset(html_id, file_path=ruta, use_default_filename=False)
        return f'reportes/fastqc/{nombre_archivo}'
    except Exception:
        return None

def _descargar_reporte_quast(gi, html_id, nombre_archivo):
    """Descarga el HTML de QUAST y lo guarda en media/reportes/quast/"""
    try:
        if not html_id:
            return None
        carpeta = os.path.join(settings.MEDIA_ROOT, 'reportes', 'quast')
        os.makedirs(carpeta, exist_ok=True)
        ruta = os.path.join(carpeta, nombre_archivo)
        gi.datasets.download_dataset(html_id, file_path=ruta, use_default_filename=False)
        return f'reportes/quast/{nombre_archivo}'
    except Exception:
        return None

def ejecutar_workflow(request):
    api_key = get_api_key(request)
    gi = GalaxyInstance(url=GALAXY_URL, key=api_key)
    histories = gi.histories.get_histories()

    if request.method == 'POST':
        nameHistory = request.POST.get('nombre_historia')
        if not nameHistory:
            return render(request, "error.html", {"mensaje": "No se seleccionó ninguna historia."})

        history_id = None
        for history in histories:
            if history["name"] == nameHistory:
                history_id = history["id"]
                break

        if not history_id:
            return render(request, "error.html", {"mensaje": "Historia no encontrada."})

        idDataset  = request.POST.get('id_dataset')
        idDataset2 = request.POST.get('id_dataset2')
        idGenoma   = request.POST.get('id_genoma')

        datasets_raw   = gi.histories.show_history(history_id, contents=True)
        datasets       = [d for d in datasets_raw if (not d.get("deleted", False)) and d.get("visible", True)]
        datasets_fastq = [d for d in datasets if d["name"].lower().endswith((".fastq", ".fq", ".fastq.gz"))]
        genomas        = [d for d in datasets if d["name"].lower().endswith(".fasta")]

        if not (idDataset and idDataset2 and idGenoma):
            return render(request, "datasetsHistoria.html", {
                "datasets": datasets,
                "datasets_fastq": datasets_fastq,
                "history_id": history_id,
                "genomas": genomas,
                "nombre_historia": nameHistory
            })

        datasetID = datasetID2 = genomaId = None
        for dataset in datasets:
            if dataset['id'] == idDataset:
                datasetID = idDataset
            elif dataset['id'] == idDataset2:
                datasetID2 = idDataset2
            elif dataset['id'] == idGenoma:
                genomaId = idGenoma

        if not (datasetID and datasetID2 and genomaId):
            return render(request, "error.html", {"mensaje": "Dataset no encontrado."})

        session_key = f"{request.user.id}_{history_id}"
        _pipeline_state[session_key] = {
            "eventos": [], "terminado": False, "cancelado": False, "job_activo": None
        }

        t = threading.Thread(
            target=_run_pipeline,
            args=(session_key, history_id, datasetID, datasetID2, genomaId, api_key, request.user.username, nameHistory),
            daemon=True
        )
        t.start()

        nombre_encoded = urllib.parse.quote(nameHistory)
        return redirect(
            f"/pipeline_progress_view/?session_key={session_key}"
            f"&history_id={history_id}"
            f"&nombre_historia={nombre_encoded}"
        )

    return render(request, "ejecutar_herramienta/ejecutar_workflow.html", {"histories": histories})


def pipeline_progress_view(request):
    nombre_historia = request.GET.get('nombre_historia', '')
    session_key     = request.GET.get('session_key', '')
    history_id      = request.GET.get('history_id', '')
    return render(request, "progreso_pipeline.html", {
        "nombre_historia": nombre_historia,
        "session_key": session_key,
        "history_id": history_id,
    })


def pipeline_progress(request):
    session_key = request.GET.get('session_key', '')

    def event_stream():
        ultimo = 0
        while True:
            state = _pipeline_state.get(session_key)
            if not state:
                yield "data: {}\n\n"
                break
            eventos = state["eventos"]
            while ultimo < len(eventos):
                yield f"data: {json.dumps(eventos[ultimo])}\n\n"
                ultimo += 1
            if state["terminado"] and ultimo >= len(eventos):
                break
            time.sleep(1)

    return StreamingHttpResponse(event_stream(), content_type="text/event-stream")


def cancelar_pipeline(request):
    if request.method == "POST":
        session_key = request.POST.get("session_key", "")
        state = _pipeline_state.get(session_key)
        if state:
            state["cancelado"] = True
            job_id = state.get("job_activo")
            if job_id:
                try:
                    api_key = get_api_key(request)
                    gi = GalaxyInstance(url=GALAXY_URL, key=api_key)
                    gi.jobs.cancel_job(job_id)
                except Exception:
                    pass
        return JsonResponse({"ok": True})
    return JsonResponse({"ok": False})


def _run_pipeline(session_key, history_id, datasetID, datasetID2, genomaId, api_key, usuario, nombre_historia):
    gi = GalaxyInstance(url=GALAXY_URL, key=api_key)
    tiempos = {}

    def push(paso, estado, detalle=""):
        _pipeline_state[session_key]["eventos"].append({
            "paso": paso, "estado": estado, "detalle": detalle
        })

    def push_fin(resultado_id=None):
        ev = {"fin": True}
        if resultado_id:
            ev["resultado_id"] = resultado_id
        _pipeline_state[session_key]["eventos"].append(ev)
        _pipeline_state[session_key]["terminado"] = True

    def push_error(paso, msg):
        _pipeline_state[session_key]["eventos"].append({
            "paso": paso, "estado": "error", "detalle": msg
        })
        _pipeline_state[session_key]["terminado"] = True

    try:
        t0 = time.time()

        push("fastqc_inicial", "running")
        t = time.time()
        fastqc_inicial = ejecutar_fastqc(history_id, [datasetID, datasetID2], api_key, session_key)
        tiempos["FastQC Inicial"] = int(time.time() - t)
        push("fastqc_inicial", "done")

        push("bowtie", "running")
        t = time.time()
        _, _, unaligned_R1, unaligned_R2 = ejecutar_bowtie(history_id, datasetID, datasetID2, genomaId, api_key, session_key)
        tiempos["Bowtie2"] = int(time.time() - t)
        push("bowtie", "done")

        push("trimmomatic", "running")
        t = time.time()
        _, _, paired_R1, paired_R2 = ejecutar_trimmomatic(history_id, unaligned_R1, unaligned_R2, api_key, session_key)
        tiempos["Trimmomatic"] = int(time.time() - t)
        push("trimmomatic", "done")

        push("fastqc_final", "running")
        t = time.time()
        fastqc_final = ejecutar_fastqc(history_id, [paired_R1, paired_R2], api_key, session_key)
        tiempos["FastQC Final"] = int(time.time() - t)
        push("fastqc_final", "done")

        push("spades", "running")
        t = time.time()
        _, _, spades_contigs = ejecutar_shovill(history_id, paired_R1, paired_R2, "spades", api_key, session_key)
        tiempos["SPAdes"] = int(time.time() - t)
        push("spades", "done")

        push("velvet", "running")
        t = time.time()
        _, _, velvet_contigs = ejecutar_shovill(history_id, paired_R1, paired_R2, "velvet", api_key, session_key)
        tiempos["Velvet"] = int(time.time() - t)
        push("velvet", "done")

        push("quast", "running")
        t = time.time()
        quast_results, winner, datasets_calidad, quast_html_ids = ejecutar_quast(
            history_id, [spades_contigs, velvet_contigs], api_key, session_key
        )
        tiempos["QUAST"] = int(time.time() - t)
        push("quast", "done")

        push("augustus", "running")
        t = time.time()
        ejecutar_augustus(history_id, winner, api_key, session_key)
        tiempos["Augustus"] = int(time.time() - t)
        push("augustus", "done")

        duracion_total = int(time.time() - t0)

        # --- Descargar reportes ---
        datasets_list = list(fastqc_inicial.keys())
        r_fastqc_r1_i = _descargar_reporte_fastqc(gi, fastqc_inicial.get(datasets_list[0], {}), f"fastqc_inicial_r1_{history_id}.html") if len(datasets_list) > 0 else None
        r_fastqc_r2_i = _descargar_reporte_fastqc(gi, fastqc_inicial.get(datasets_list[1], {}), f"fastqc_inicial_r2_{history_id}.html") if len(datasets_list) > 1 else None
        datasets_final = list(fastqc_final.keys())
        r_fastqc_r1_f = _descargar_reporte_fastqc(gi, fastqc_final.get(datasets_final[0], {}), f"fastqc_final_r1_{history_id}.html") if len(datasets_final) > 0 else None
        r_fastqc_r2_f = _descargar_reporte_fastqc(gi, fastqc_final.get(datasets_final[1], {}), f"fastqc_final_r2_{history_id}.html") if len(datasets_final) > 1 else None
        r_quast_spades = _descargar_reporte_quast(gi, quast_html_ids.get(spades_contigs), f"quast_spades_{history_id}.html")
        r_quast_velvet = _descargar_reporte_quast(gi, quast_html_ids.get(velvet_contigs), f"quast_velvet_{history_id}.html")

        # --- Guardar en PostgreSQL ---
        ganador_nombre = 'spades' if winner == spades_contigs else 'velvet'
        n50_sp = datasets_calidad.get(spades_contigs, {}).get('N50')
        l50_sp = datasets_calidad.get(spades_contigs, {}).get('L50')
        n50_vl = datasets_calidad.get(velvet_contigs, {}).get('N50')
        l50_vl = datasets_calidad.get(velvet_contigs, {}).get('L50')

        try:
            from resultados_app.models import ResultadoPipeline
            resultado = ResultadoPipeline(
                usuario=usuario,
                nombre_historia=nombre_historia,
                history_id=history_id,
                ganador=ganador_nombre,
                n50_spades=n50_sp,
                l50_spades=l50_sp,
                n50_velvet=n50_vl,
                l50_velvet=l50_vl,
                duracion_total=duracion_total,
            )
            if r_fastqc_r1_i: resultado.reporte_fastqc_r1_inicial = r_fastqc_r1_i
            if r_fastqc_r2_i: resultado.reporte_fastqc_r2_inicial = r_fastqc_r2_i
            if r_fastqc_r1_f: resultado.reporte_fastqc_r1_final = r_fastqc_r1_f
            if r_fastqc_r2_f: resultado.reporte_fastqc_r2_final = r_fastqc_r2_f
            if r_quast_spades: resultado.reporte_quast_spades = r_quast_spades
            if r_quast_velvet: resultado.reporte_quast_velvet = r_quast_velvet
            resultado.save(using='resultados')
            resultado_id = resultado.id
        except Exception as e:
            resultado_id = None

        push_fin(resultado_id=resultado_id)

    except Exception as e:
        msg = str(e)
        if "cancelado" in msg.lower():
            _pipeline_state[session_key]["eventos"].append({"cancelado": True})
            _pipeline_state[session_key]["terminado"] = True
            return
        eventos = _pipeline_state[session_key]["eventos"]
        paso_activo = None
        for ev in reversed(eventos):
            if ev.get("estado") == "running":
                paso_activo = ev.get("paso")
                break
        push_error(paso_activo or "fastqc_inicial", msg)


# ── Vista historial de resultados ───────────────────────────────────────────
def historial_resultados(request):
    from resultados_app.models import ResultadoPipeline
    resultados = ResultadoPipeline.objects.using('resultados').filter(usuario=request.user.username)
    return render(request, "historial_resultados.html", {"resultados": resultados})


def ver_reportes(request, resultado_id):
    from resultados_app.models import ResultadoPipeline
    resultado = ResultadoPipeline.objects.using('resultados').get(id=resultado_id)
    return render(request, "ver_reportes.html", {"resultado": resultado})


# ── Funciones auxiliares existentes ─────────────────────────────────────────
def ejecutar_trimmomatic_single(request, history_id):
    api_key = get_api_key(request)
    gi = GalaxyInstance(url=GALAXY_URL, key=api_key)
    history_info = gi.histories.show_history(history_id, keys=["name"])
    nameHistory = history_info["name"]
    idDataset = request.POST.get('id_dataset')
    idDataset2 = request.POST.get('id_dataset2')
    datasets_raw = gi.histories.show_history(history_id, contents=True)
    datasets = [d for d in datasets_raw if (not d.get("deleted", False)) and d.get("visible", True)]
    datasets_fastq = [d for d in datasets if d["name"].lower().endswith((".fastq", ".fq", ".fastq.gz"))]
    if not (idDataset and idDataset2):
        return render(request, "ejecutar_herramienta/ejecutar_trimmomatic_single.html", {
            "datasets": datasets, "datasets_fastq": datasets_fastq,
            "history_id": history_id, "nombre_historia": nameHistory
        })
    datasetID = datasetID2 = None
    for dataset in datasets:
        if dataset['id'] == idDataset: datasetID = idDataset
        elif dataset['id'] == idDataset2: datasetID2 = idDataset2
    if not (datasetID and datasetID2):
        return render(request, "error.html", {"mensaje": "Dataset no encontrado."})
    tool_inputs = {
        "readtype|single_or_paired": "pair_of_files",
        "readtype|fastq_r1_in": {"src": "hda", "id": idDataset},
        "readtype|fastq_r2_in": {"src": "hda", "id": idDataset2},
        "illuminaclip|do_illuminaclip": "no",
    }
    job = gi.tools.run_tool(
        history_id=history_id,
        tool_id="toolshed.g2.bx.psu.edu/repos/pjbriggs/trimmomatic/trimmomatic/0.39+galaxy2",
        tool_inputs=tool_inputs,
    )
    job_id = job["jobs"][0]["id"]
    esperar_finalizacion(gi, job_id)
    info = gi.jobs.show_job(job_id)
    return JsonResponse({"info": info}, safe=False)

def show_dataset(request, id):
    api_key = get_api_key(request)
    gi = GalaxyInstance(url=GALAXY_URL, key=api_key)
    return JsonResponse(gi.datasets.show_dataset(id))

def get_jobs(request, id):
    api_key = get_api_key(request)
    gi = GalaxyInstance(url=GALAXY_URL, key=api_key)
    return JsonResponse(gi.jobs.get_outputs(id), safe=False)

def get_jobs_history(request, id):
    api_key = get_api_key(request)
    gi = GalaxyInstance(url=GALAXY_URL, key=api_key)
    return JsonResponse(gi.jobs.get_jobs(history_id=id), safe=False)

def get_inputs_job(request, id):
    api_key = get_api_key(request)
    gi = GalaxyInstance(url=GALAXY_URL, key=api_key)
    return JsonResponse(gi.jobs.get_inputs(job_id=id), safe=False)

def get_outputs_job(request, id):
    api_key = get_api_key(request)
    gi = GalaxyInstance(url=GALAXY_URL, key=api_key)
    return JsonResponse(gi.jobs.get_outputs(job_id=id), safe=False)

def ver_parametros_permitidos_tool(request, id_tool):
    api_key = get_api_key(request)
    gi = GalaxyInstance(url=GALAXY_URL, key=api_key)
    return JsonResponse(gi.tools.show_tool(tool_id=id_tool, io_details=True))
