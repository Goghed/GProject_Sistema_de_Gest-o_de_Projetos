from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from .models import Notification


@login_required
def notifications_list(request):
    notifs = request.user.notifications.all()[:60]
    unread_count = request.user.notifications.filter(read=False).count()
    return render(request, "notifications/list.html", {
        "notifications": notifs,
        "unread_count":  unread_count,
    })


@login_required
@require_POST
def mark_read(request, pk):
    Notification.objects.filter(pk=pk, user=request.user).update(read=True)
    return JsonResponse({"ok": True})


@login_required
@require_POST
def mark_all_read(request):
    count = request.user.notifications.filter(read=False).update(read=True)
    return JsonResponse({"ok": True, "count": count})


@login_required
@require_POST
def clear_all(request):
    count, _ = request.user.notifications.all().delete()
    return JsonResponse({"ok": True, "count": count})
