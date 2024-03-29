#!/usr/bin/env zsh

fit_model () {
    # run with testing populations in each order
    ./fit_models.py --model_type $1 --train_pop $2 --test_pop_1 $3 --test_pop_2 $4
    ./fit_models.py --model_type $1 --train_pop $2 --test_pop_1 $4 --test_pop_2 $3

    # ./fit_models.py --model_type $1 --train_pop $2 --test_pop_1 $3 --test_pop_2 $4 --blosum_inference
    # ./fit_models.py --model_type $1 --train_pop $2 --test_pop_1 $4 --test_pop_2 $3 --blosum_inference

    # ./fit_models.py --model_type $1 --train_pop $2 --test_pop_1 $3 --test_pop_2 $4 --HMM_inference
    # ./fit_models.py --model_type $1 --train_pop $2 --test_pop_1 $4 --test_pop_2 $3 --HMM_inference

    # ./fit_models.py --model_type $1 --train_pop $2 --test_pop_1 $3 --test_pop_2 $4 --HMM_MIC_inference
    # ./fit_models.py --model_type $1 --train_pop $2 --test_pop_1 $4 --test_pop_2 $3 --HMM_MIC_inference

    # ./fit_models.py --model_type $1 --train_pop $2 --test_pop_1 $3 --test_pop_2 $4 --blosum_inference --just_HMM_scores
    # ./fit_models.py --model_type $1 --train_pop $2 --test_pop_1 $4 --test_pop_2 $3 --blosum_inference --just_HMM_scores

}

POPS=("cdc" "pmen" "maela")
for training_pop in $POPS
do
    TEST_POPS=("${(@)POPS:#$training_pop}") # subset array by removing training pop
    test_pop_1=${TEST_POPS[@]:0:1}
    test_pop_2=${TEST_POPS[@]:1:1}

    fit_model "random_forest" $training_pop $test_pop_1 $test_pop_2
    fit_model "elastic_net" $training_pop $test_pop_1 $test_pop_2
    fit_model "DBSCAN" $training_pop $test_pop_1 $test_pop_2
    fit_model "DBSCAN_with_UMAP" $training_pop $test_pop_1 $test_pop_2

done
