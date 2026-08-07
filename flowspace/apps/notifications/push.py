# apps/notifications/push.py
"""
Utilitário para enviar notificações push via Expo Push API.
Documentação: https://docs.expo.dev/push-notifications/sending-notifications/
"""
import logging
import requests

logger = logging.getLogger(__name__)

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"


def send_push(tokens: list[str], title: str, body: str, data: dict = None):
    """
    Envia notificação push para uma lista de tokens Expo.
    tokens: lista de strings no formato 'ExponentPushToken[...]'
    """
    if not tokens:
        return

    messages = [
        {
            "to":    token,
            "sound": "default",
            "title": title,
            "body":  body,
            "data":  data or {},
        }
        for token in tokens
        if token and token.startswith("ExponentPushToken")
    ]

    if not messages:
        return

    try:
        resp = requests.post(
            EXPO_PUSH_URL,
            json=messages,
            headers={
                "Accept":       "application/json",
                "Content-Type": "application/json",
            },
            timeout=10,
        )
        resp.raise_for_status()
        result = resp.json()
        # Log erros por token
        for item in result.get("data", []):
            if item.get("status") == "error":
                logger.warning("Expo push error: %s", item.get("message"))
    except Exception as exc:
        logger.error("Falha ao enviar push notification: %s", exc)


def notify_task_progress(task, actor, new_status: str):
    """
    Notifica todos os membros do projeto quando uma tarefa muda de status.
    Cria notificação no banco E envia push para o celular.
    """
    from apps.notifications.models import Notification

    STATUS_LABELS = {
        "in_progress": "iniciou",
        "review":      "enviou para revisão",
        "done":        "concluiu",
    }
    label = STATUS_LABELS.get(new_status, f"atualizou para {new_status}")

    title   = f"📋 {task.project.name}"
    message = f"{actor} {label} a tarefa «{task.title}»"
    link    = f"/tasks/{task.pk}/"

    # Todos os membros do projeto, exceto quem fez a ação
    members = task.project.members.exclude(id=actor.id)

    tokens = []
    for member in members:
        # Notificação no banco (sino do sistema web)
        Notification.objects.create(user=member, message=message, link=link)
        # Coleta token push
        if member.expo_push_token:
            tokens.append(member.expo_push_token)

    # Envia push
    send_push(
        tokens=tokens,
        title=title,
        body=message,
        data={"task_id": str(task.pk), "project_id": str(task.project.pk)},
    )
