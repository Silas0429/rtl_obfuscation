module t104_core (
    input logic clk,
    output logic result
);
    `T104_SIG_DECL(macro_signal);
    logic clean_signal;
    `T104_UNIQUE_BODY_DECL;

    t104_bus bus (
        .clk(clk)
    );
    t104_payload_t payload;
    t104_union_t union_value;

    t104_child u_child (
        .clk(clk),
        .child_in(macro_signal),
        .child_out(result)
    );

    assign clean_signal = macro_signal & `T104_CONST;
    assign `T104_IF_REF(bus, data) = clean_signal;
    assign `T104_IF_REF(bus, valid) = clean_signal;
    assign `T104_STRUCT_REF(payload, struct_field) = clean_signal;
    assign union_value.union_field = clean_signal;
    assign `T104_UNIQUE_BODY_REF = clean_signal;
    assign result = `T104_SIG_REF(macro_signal);

    generate
        if (1) begin : gen_macro_argument
            logic gen_arg_signal;
            assign gen_arg_signal = clean_signal;
            t104_child u_gen_argument (
                .clk(clk),
                `T104_GEN_NAMED_CONN(gen_arg_signal),
                .child_out()
            );
        end
        if (1) begin : gen_macro_body_a
            logic gen_body_signal;
            assign gen_body_signal = clean_signal;
            t104_child u_gen_body_a (
                .clk(clk),
                `T104_GEN_BODY_CONN,
                .child_out()
            );
        end
        if (1) begin : gen_macro_body_b
            logic gen_body_signal;
            assign gen_body_signal = clean_signal;
            t104_child u_gen_body_b (
                .clk(clk),
                `T104_GEN_BODY_CONN,
                .child_out()
            );
        end
    endgenerate
endmodule
