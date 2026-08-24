interface t104_bus (
    input logic clk
);
    `T104_IF_MEMBER(data);
    `T104_IF_MEMBER(valid);

    modport consumer (
        input clk,
        input data,
        output valid
    );
endinterface
