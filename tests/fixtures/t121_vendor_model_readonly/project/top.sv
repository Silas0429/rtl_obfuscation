`timescale 1ns/1ps
module t121_top (
    input  logic [7:0] data_i,
    output logic [7:0] data_o
);
    logic [7:0] child_data;
    logic [7:0] external_data;
    logic diagnostic_data;
    logic [7:0] project_signal;

    t121_child user_child (
        .data_i(data_i),
        .data_o(child_data)
    );
    t121_clean_wrapper external_wrapper (
        .data_i(data_i),
        .data_o(external_data)
    );
    t121_diagnostic_cell diagnostic_instance (
        .data_i(data_i[0]),
        .data_o(diagnostic_data)
    );

    assign project_signal = child_data ^ external_data;
    assign data_o = project_signal ^ {8{diagnostic_data}};
endmodule
