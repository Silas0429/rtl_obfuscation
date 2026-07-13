module t009_task_argument (
    input  logic [3:0] input_data,
    output logic [3:0] output_data
);

    task automatic drive_value(
        input  logic [3:0] task_data,
        output logic [3:0] task_result
    );
        task_result = task_data ^ 4'h5;
    endtask

    always_comb begin
        drive_value(input_data, output_data);
    end

endmodule
