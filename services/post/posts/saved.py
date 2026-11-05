"""Saved collections (track T4): the owner's named folders of saved items.

Every save lands in a collection: the default one ("Saved", created on first
use) unless the saver picks another. Collections are private to their owner:
another account's collection id is 404, never 403. Deleting a collection
keeps its items: they move back to the default collection. The default
collection itself can be neither renamed nor deleted.

Saves are private state and emit no events.
"""

from __future__ import annotations

from django.db import transaction
from django.db.models import Count

from tara_common.exceptions import TaraAPIError

from .models import Post, SavedCollection, SavedItem
from .services import _default_collection

MAX_COLLECTIONS = 100
NAME_MAX = 80


def _not_found() -> TaraAPIError:
    return TaraAPIError("Collection not found.", code="not_found", http_status_code=404)


def _clean_name(name: str) -> str:
    value = " ".join((name or "").split())
    if not value:
        raise TaraAPIError(
            "A collection needs a name.", code="validation_error", http_status_code=400
        )
    if len(value) > NAME_MAX:
        raise TaraAPIError(
            f"A collection name has at most {NAME_MAX} characters.",
            code="validation_error",
            http_status_code=400,
        )
    return value


def own_collection(owner_id: str, collection_id, *, lock: bool = False) -> SavedCollection:
    qs = SavedCollection.objects.filter(id=collection_id, owner_id=owner_id)
    collection = (qs.select_for_update() if lock else qs).first()
    if collection is None:
        raise _not_found()
    return collection


def list_collections(owner_id: str) -> list[SavedCollection]:
    """The default collection first, then the others oldest first, each with
    ``item_count``. The default one exists from the first call."""
    default = _default_collection(owner_id)
    rows = list(
        SavedCollection.objects.filter(owner_id=owner_id)
        .annotate(item_count=Count("items"))
        .order_by("created_at", "id")
    )
    # Extra default rows (two first saves at once) are shown as one.
    return [c for c in rows if c.id == default.id] + [c for c in rows if not c.is_default]


def create_collection(owner_id: str, name: str) -> SavedCollection:
    value = _clean_name(name)
    if (
        SavedCollection.objects.filter(owner_id=owner_id, is_default=False).count()
        >= MAX_COLLECTIONS
    ):
        raise TaraAPIError(
            f"You can have at most {MAX_COLLECTIONS} collections.",
            code="limit_reached",
            http_status_code=400,
        )
    _default_collection(owner_id)
    collection = SavedCollection.objects.create(owner_id=owner_id, name=value, is_default=False)
    collection.item_count = 0
    return collection


def _refuse_default(collection: SavedCollection) -> None:
    if collection.is_default:
        raise TaraAPIError(
            "The default collection cannot be changed.",
            code="default_collection",
            http_status_code=400,
        )


def rename_collection(owner_id: str, collection_id, name: str) -> SavedCollection:
    value = _clean_name(name)
    with transaction.atomic():
        collection = own_collection(owner_id, collection_id, lock=True)
        _refuse_default(collection)
        if collection.name != value:
            collection.name = value
            collection.save(update_fields=["name"])
    collection.item_count = collection.items.count()
    return collection


def delete_collection(owner_id: str, collection_id) -> None:
    """Its items go back to the default collection; nothing is unsaved."""
    with transaction.atomic():
        collection = own_collection(owner_id, collection_id, lock=True)
        _refuse_default(collection)
        default = _default_collection(owner_id)
        SavedItem.objects.filter(owner_id=owner_id, collection=collection).update(
            collection=default
        )
        collection.delete()


def save_into(owner_id: str, item_type: str, item_id: str, collection_id=None) -> SavedItem:
    """Save an item, or move it when it is saved already. Without a collection
    a new save goes to the default one and an existing save stays where it is."""
    with transaction.atomic():
        target = own_collection(owner_id, collection_id) if collection_id else None
        item = (
            SavedItem.objects.select_for_update()
            .filter(owner_id=owner_id, item_type=item_type, item_id=item_id)
            .first()
        )
        if item is None:
            item, _ = SavedItem.objects.get_or_create(
                owner_id=owner_id,
                item_type=item_type,
                item_id=item_id,
                defaults={"collection": target or _default_collection(owner_id)},
            )
        if target is not None and item.collection_id != target.id:
            item.collection = target
            item.save(update_fields=["collection"])
    return item


def move_saved_item(owner_id: str, saved_id, collection_id) -> SavedItem:
    """Move one of my saved items (by its saved-item id) to one of my collections."""
    with transaction.atomic():
        item = SavedItem.objects.select_for_update().filter(id=saved_id, owner_id=owner_id).first()
        if item is None:
            raise TaraAPIError("Saved item not found.", code="not_found", http_status_code=404)
        target = (
            own_collection(owner_id, collection_id)
            if collection_id
            else _default_collection(owner_id)
        )
        if item.collection_id != target.id:
            item.collection = target
            item.save(update_fields=["collection"])
    return item


def list_saved(owner_id: str, item_type: str | None = None, collection_id=None, *, post_type=None):
    """My saved items, newest first, optionally one type or one collection.

    ``post_type`` keeps saved posts of one kind (``reel``: a profile's "Saved
    reels"); it implies ``item_type=post``. Visibility is checked when the
    client loads the posts themselves (``/posts/batch/``)."""
    qs = SavedItem.objects.filter(owner_id=owner_id)
    if post_type:
        item_type = "post"
        qs = qs.filter(
            item_id__in=Post.objects.filter(type=post_type, deleted_at__isnull=True).values("id")
        )
    if item_type:
        qs = qs.filter(item_type=item_type)
    if collection_id:
        qs = qs.filter(collection=own_collection(owner_id, collection_id))
    return qs.order_by("-created_at")
