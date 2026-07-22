from django.db import models


class RagProject(models.Model):
    name = models.CharField(max_length=200)
    short_name = models.CharField(max_length=50)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "rag_project"

    def __str__(self):
        return f"{self.name} ({self.short_name})"


class Experiment(models.Model):
    project = models.ForeignKey(
        RagProject,
        on_delete=models.CASCADE,
        default=1,
    )
    name = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    parameters = models.JSONField()
    spec_snapshot = models.TextField()

    mrr = models.FloatField()
    recall_at_5 = models.FloatField()
    is_starred = models.BooleanField(default=False)

    class Meta:
        db_table = "rag_experiment"

    def __str__(self):
        return f"Experiment {self.id} ({self.created_at})"