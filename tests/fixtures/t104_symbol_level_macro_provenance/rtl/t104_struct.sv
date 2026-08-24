typedef struct packed {
    `T104_STRUCT_FIELD(struct_field);
    logic clean_field;
} t104_payload_t;

typedef union packed {
    `T104_UNION_FIELD(union_field);
    t104_payload_t payload;
} t104_union_t;
