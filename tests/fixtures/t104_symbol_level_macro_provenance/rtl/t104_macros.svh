`define T104_CONST 1'b1
`define T104_SIG_DECL(name) logic name
`define T104_SIG_REF(name) name
`define T104_PORT_DECL(name) input logic name
`define T104_IF_MEMBER(name) logic name
`define T104_IF_REF(base, member) base.member
`define T104_STRUCT_FIELD(name) logic name
`define T104_STRUCT_REF(base, member) base.member
`define T104_UNION_FIELD(name) logic [1:0] name
`define T104_UNIQUE_BODY_DECL logic unique_body_signal
`define T104_UNIQUE_BODY_REF unique_body_signal
`define T104_CONFLICT_BODY_REF conflict_body_signal
`define T104_PASTE(prefix, suffix) prefix``suffix
`define T104_GEN_DECL(prefix, suffix) logic prefix``suffix
`define T104_GEN_NAMED_CONN(name) .child_in(name)
`define T104_GEN_BODY_CONN .child_in(gen_body_signal)
