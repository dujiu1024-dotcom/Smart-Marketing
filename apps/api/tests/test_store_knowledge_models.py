from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint

from store_operator.models import Base


def test_store_knowledge_tables_are_registered_with_tenant_keys() -> None:
    expected = {
        "store_profiles",
        "products",
        "offers",
        "brand_guidelines",
        "audience_profiles",
        "knowledge_items",
        "media_assets",
        "upload_intents",
        "store_record_revisions",
        "offer_products",
        "product_media_assets",
        "knowledge_item_products",
        "audience_profile_products",
    }
    assert expected <= set(Base.metadata.tables)

    for name in expected - {
        "offer_products",
        "product_media_assets",
        "knowledge_item_products",
        "audience_profile_products",
    }:
        table = Base.metadata.tables[name]
        assert table.c.store_id.nullable is False
        assert table.c.id.primary_key is True


def test_singleton_store_records_and_product_price_constraints_exist() -> None:
    for name in ("store_profiles", "brand_guidelines"):
        table = Base.metadata.tables[name]
        assert any(
            isinstance(constraint, UniqueConstraint)
            and tuple(column.name for column in constraint.columns) == ("store_id",)
            for constraint in table.constraints
        )

    products = Base.metadata.tables["products"]
    check_sql = {str(c.sqltext) for c in products.constraints if isinstance(c, CheckConstraint)}
    assert any("price_amount" in sql and "currency" in sql for sql in check_sql)
    assert any("price_amount" in sql and ">= 0" in sql for sql in check_sql)


def test_cross_record_relations_use_composite_store_foreign_keys() -> None:
    for name in (
        "offer_products",
        "product_media_assets",
        "knowledge_item_products",
        "audience_profile_products",
    ):
        table = Base.metadata.tables[name]
        composite = [
            constraint
            for constraint in table.constraints
            if isinstance(constraint, ForeignKeyConstraint)
        ]
        assert len(composite) == 2
        assert all(
            [element.parent.name for element in constraint.elements][0] == "store_id"
            for constraint in composite
        )


def test_media_derivatives_and_brand_logo_are_store_scoped() -> None:
    media = Base.metadata.tables["media_assets"]
    parent_fk = [
        constraint
        for constraint in media.constraints
        if isinstance(constraint, ForeignKeyConstraint)
        and [element.parent.name for element in constraint.elements]
        == ["store_id", "parent_asset_id"]
    ]
    assert len(parent_fk) == 1

    brand = Base.metadata.tables["brand_guidelines"]
    logo_fk = [
        constraint
        for constraint in brand.constraints
        if isinstance(constraint, ForeignKeyConstraint)
        and [element.parent.name for element in constraint.elements]
        == ["store_id", "logo_asset_id"]
    ]
    assert len(logo_fk) == 1
