{{- define "gold.fullname" -}}{{ .Release.Name }}{{- end -}}

{{- define "gold.labels" -}}
app.kubernetes.io/part-of: gold
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
{{- end -}}

{{/* The endpoint every model call goes to. */}}
{{- define "gold.llmBaseUrl" -}}
{{- if .Values.llm.baseUrl -}}{{ .Values.llm.baseUrl }}
{{- else if .Values.gateway.enabled -}}http://{{ include "gold.fullname" . }}-gateway:4000/v1
{{- else -}}http://{{ include "gold.fullname" . }}-scripted-model:8000/v1
{{- end -}}
{{- end -}}

{{- define "gold.llmSecret" -}}
{{- .Values.llm.existingSecret | default (printf "%s-llm" (include "gold.fullname" .)) -}}
{{- end -}}

{{- define "gold.dbSecret" -}}
{{- .Values.database.existingSecret | default (printf "%s-db" (include "gold.fullname" .)) -}}
{{- end -}}
