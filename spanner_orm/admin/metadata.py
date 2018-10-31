# Copyright 2018 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# python3
"""Retrieves database metadata"""

from collections import defaultdict
from spanner_orm.admin.api import DatabaseAdminApi
from spanner_orm.condition import EqualityCondition
from spanner_orm.condition import InequalityCondition
from spanner_orm.condition import OrderByCondition
from spanner_orm.condition import OrderType
from spanner_orm.model import Model
from spanner_orm.schemas.column import ColumnSchema
from spanner_orm.schemas.index import IndexSchema
from spanner_orm.schemas.index_column import IndexColumnSchema
from spanner_orm.update import ColumnUpdate
from spanner_orm.update import CreateTableUpdate
from spanner_orm.update import IndexUpdate


class DatabaseMetadata(object):
  """Retrieve table metadata from Spanner and returns it in a usable format"""

  @classmethod
  def column_update(cls, schema_change):
    assert isinstance(schema_change, ColumnUpdate)
    model = cls.models()[schema_change.table()]
    schema_change.validate(model)

    DatabaseAdminApi.update_schema(schema_change.ddl(model))

  @classmethod
  def create_table(cls, schema_change):
    assert isinstance(schema_change, CreateTableUpdate)
    all_models = cls.models()
    assert schema_change.table() not in all_models
    schema_change.validate()

    DatabaseAdminApi.update_schema(schema_change.ddl())

  @classmethod
  def index_update(cls, schema_change):
    assert isinstance(schema_change, IndexUpdate)
    model = cls.models()[schema_change.table()]
    schema_change.validate(model)

    DatabaseAdminApi.update_schema(schema_change.ddl(model))

  @classmethod
  def models(cls, transaction=None):
    """Constructs model classes from Spanner database schema"""
    tables = cls._tables(transaction)
    indexes = cls._indexes(transaction)
    results = {}

    def make_method(retval):
      return lambda: retval

    def make_classmethod(retval):
      return classmethod(lambda _: retval)

    for table_name, schema in tables.items():
      primary_index = indexes[table_name]['PRIMARY_KEY']['columns']
      klass = type(
          'Model_{}'.format(table_name), (Model,), {
              'primary_index_keys': make_method(primary_index),
              'schema': make_classmethod(schema),
              'table': make_classmethod(table_name)
          })
      results[table_name] = klass
    return results

  @classmethod
  def _tables(cls, transaction=None):
    """Compiles table information from column schema"""
    tables = defaultdict(dict)
    schemas = ColumnSchema.where(transaction,
                                 EqualityCondition('table_catalog', ''),
                                 EqualityCondition('table_schema', ''))
    for schema in schemas:
      tables[schema.table_name][schema.column_name] = schema.type()
    return tables

  @classmethod
  def _indexes(cls, transaction=None):
    """Compiles index information from index and index columns schemas"""
    # ordinal_position is the position of the column in the indicated index.
    # Results are ordered by that so the index columns are added in the correct
    # order. None indicates that the key isn't really a part of the index, so we
    # skip those
    index_column_schemas = IndexColumnSchema.where(
        transaction, EqualityCondition('table_catalog', ''),
        EqualityCondition('table_schema', ''),
        InequalityCondition('ordinal_position', None),
        OrderByCondition(('ordinal_position', OrderType.ASC)))

    index_columns = defaultdict(list)
    for schema in index_column_schemas:
      key = (schema.table_name, schema.index_name)
      index_columns[key].append(schema.column_name)

    index_schemas = IndexSchema.where(transaction,
                                      EqualityCondition('table_catalog', ''),
                                      EqualityCondition('table_schema', ''))
    indexes = defaultdict(dict)
    for schema in index_schemas:
      indexes[schema.table_name][schema.index_name] = {
          'columns': index_columns[(schema.table_name, schema.index_name)],
          'type': schema.index_type,
          'unique': schema.is_unique,
          'state': schema.index_state
      }

    return indexes