export interface ColumnMeta {
  name: string;
  data_type: string;
  is_partition_key?: boolean;
  comment?: string;
}

export interface TableMeta {
  table_name: string;
  database: string;
  columns: ColumnMeta[];
}

export interface CatalogSyncResponse {
  tables_synced: number;
  vectors_indexed: number;
  table_names: string[];
  tables: TableMeta[];
}
